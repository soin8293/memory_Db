#!/usr/bin/env python3
"""Build a local embeddings *index* (chunks table) from nodes.jsonl.

This is step 2 of PRD_embeddings_local.md:
- writes chunk rows into SQLite
- leaves embedding columns NULL (no model/deps required)

No network calls.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path as _Path

# Allow importing memory_system as a package when running as a script.
_REPO_ROOT = str(_Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from memory_system.paths import default_embeddings_db_path, default_nodes_path


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


def chunk_text(text: str, max_chars: int = 800) -> List[str]:
    """Chunk text into ~max_chars pieces with preference for paragraph boundaries."""
    t = (text or "").strip()
    if not t:
        return []

    # Paragraph split first
    paras = [p.strip() for p in t.split("\n\n") if p.strip()]
    chunks: List[str] = []

    def push_piece(piece: str) -> None:
        piece = piece.strip()
        if not piece:
            return
        if len(piece) <= max_chars:
            chunks.append(piece)
            return
        # Sentence-ish split fallback
        parts: List[str] = []
        cur = ""
        for token in piece.replace("\n", " ").split(" "):
            if not token:
                continue
            if len(cur) + len(token) + 1 <= max_chars:
                cur = f"{cur} {token}".strip()
            else:
                if cur:
                    parts.append(cur)
                cur = token
        if cur:
            parts.append(cur)
        chunks.extend(parts)

    # Pack paragraphs into max_chars
    buf = ""
    for p in paras:
        candidate = (buf + "\n\n" + p).strip() if buf else p
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                push_piece(buf)
            buf = p
    if buf:
        push_piece(buf)

    return chunks


def ensure_schema(conn: sqlite3.Connection, nodes_path: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
          node_id TEXT NOT NULL,
          chunk_id TEXT NOT NULL,
          project_id TEXT,
          session_id TEXT,
          entity_id TEXT,
          node_type TEXT,
          source_path TEXT,
          ts TEXT,
          text TEXT NOT NULL,
          text_sha256 TEXT NOT NULL,
          meta_json TEXT,
          embedding BLOB,
          embedding_int8 BLOB,
          embedding_model TEXT,
          embedding_backend TEXT,
          created_at TEXT NOT NULL,
          PRIMARY KEY (node_id, chunk_id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(node_type)")

    # Add embedding_int8 column if it doesn't exist (migration)
    try:
        cur.execute("ALTER TABLE chunks ADD COLUMN embedding_int8 BLOB")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Full-text search (hybrid retrieval). FTS is derived; rebuildable.
    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          node_id,
          chunk_id,
          project_id,
          node_type,
          text,
          content=''
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
          k TEXT PRIMARY KEY,
          v TEXT NOT NULL
        )
        """
    )

    meta = {
        "schema_version": "1",
        "built_at": iso_now(),
        "source_nodes_path": nodes_path,
    }
    for k, v in meta.items():
        cur.execute(
            "INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)",
            (k, str(v)),
        )
    conn.commit()


def iter_nodes(nodes_path: Path) -> Iterable[Dict[str, Any]]:
    with nodes_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def build_faiss_index(conn: sqlite3.Connection, faiss_path: Path) -> None:
    """Build a FAISS IVF index from embeddings in the database.

    Uses IVF (Inverted File) index for O(sqrt(n)) approximate search.
    Falls back to flat index for small datasets.
    """
    try:
        import faiss
        import numpy as np
    except ImportError:
        print("FAISS not installed. Run: pip install faiss-cpu", file=sys.stderr)
        return

    # Load all embeddings from database
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT node_id, chunk_id, embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()

    if not rows:
        print("No embeddings found in database. Run with --embed first.", file=sys.stderr)
        return

    # Convert to numpy array
    import array
    vectors = []
    ids = []  # (node_id, chunk_id) pairs

    for node_id, chunk_id, emb_blob in rows:
        if emb_blob is None:
            continue
        arr = array.array("f")
        arr.frombytes(emb_blob)
        vectors.append(list(arr))
        ids.append(f"{node_id}:{chunk_id}")

    if not vectors:
        print("No valid embeddings found.", file=sys.stderr)
        return

    vectors_np = np.array(vectors, dtype="float32")
    n_vectors, dim = vectors_np.shape

    print(f"Building FAISS index: {n_vectors} vectors, {dim} dimensions")

    # Normalize vectors for cosine similarity (use inner product after normalization)
    faiss.normalize_L2(vectors_np)

    # Choose index type based on dataset size
    if n_vectors < 100:
        # Small dataset: use flat index (exact search)
        index = faiss.IndexFlatIP(dim)
        index.add(vectors_np)
        print(f"Built flat index (exact search) with {index.ntotal} vectors")
    else:
        # Larger dataset: use IVF index (approximate search)
        nlist = max(4, min(n_vectors // 50, 100))  # Number of clusters
        quantizer = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)

        # Train the index
        index.train(vectors_np)
        index.add(vectors_np)

        # Set search parameters
        index.nprobe = min(10, nlist)  # Number of clusters to search

        print(f"Built IVF index: {index.ntotal} vectors, {nlist} clusters, nprobe={index.nprobe}")

    # Save index and ID mapping
    faiss.write_index(index, str(faiss_path))

    # Save ID mapping as JSON
    ids_path = faiss_path.with_suffix(".ids.json")
    with ids_path.open("w") as f:
        json.dump(ids, f)

    print(f"Saved FAISS index to {faiss_path}")
    print(f"Saved ID mapping to {ids_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--nodes",
        default=str(default_nodes_path()),
        help="Path to nodes.jsonl (local-only)",
    )
    ap.add_argument(
        "--db",
        default=str(default_embeddings_db_path()),
        help="Path to embeddings sqlite db (local-only)",
    )
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete and rebuild the sqlite db",
    )
    ap.add_argument(
        "--max-chars",
        type=int,
        default=800,
        help="Max characters per chunk",
    )
    ap.add_argument(
        "--embed",
        action="store_true",
        help="Populate embeddings locally (uses a stub backend by default).",
    )
    ap.add_argument(
        "--backend",
        default="hash",
        help="Embedder backend name: hash|fastembed (default: hash).",
    )
    ap.add_argument(
        "--model",
        default=None,
        help="Model name (backend-dependent). For fastembed, e.g. BAAI/bge-small-en-v1.5",
    )
    ap.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow one-time model download during indexing (setup only).",
    )
    ap.add_argument(
        "--no-download",
        action="store_true",
        help="Disallow downloads; fail fast if model missing.",
    )
    ap.add_argument(
        "--dim",
        type=int,
        default=96,
        help="Embedding dimension (hash backend only).",
    )
    ap.add_argument(
        "--project-id",
        default=None,
        help="Optional scope/project_id filter (defaults to all).",
    )
    ap.add_argument(
        "--build-faiss",
        action="store_true",
        help="Build FAISS IVF index for O(log n) vector search.",
    )
    ap.add_argument(
        "--quantize",
        action="store_true",
        help="Store int8 quantized embeddings (4x smaller, ~0.002%% quality loss).",
    )
    ap.add_argument(
        "--build-keywords",
        action="store_true",
        help="Build keyword inverted index for fast heuristic fallback.",
    )

    args = ap.parse_args()

    nodes_path = Path(args.nodes).expanduser()
    db_path = Path(args.db).expanduser()

    if not nodes_path.exists():
        print(f"nodes.jsonl not found: {nodes_path}", file=sys.stderr)
        return 2

    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.rebuild and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn, str(nodes_path))
        cur = conn.cursor()

        inserted = 0
        skipped = 0

        # Optional embedding backend
        embedder = None
        if args.embed:
            from memory_system.embeddings.factory import get_embedder

            if args.no_download and args.allow_download:
                raise SystemExit("Choose only one: --allow-download or --no-download")
            allow_download = bool(args.allow_download)
            if args.no_download:
                allow_download = False

            embedder = get_embedder(
                args.backend,
                dim=args.dim,
                model=args.model,
                allow_download=allow_download,
            )
            print(f"EMBEDDER backend={args.backend} model={getattr(embedder,'model_name',None)} dim={getattr(embedder,'dim',None)} python={sys.executable}")

        for node in iter_nodes(nodes_path):
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                skipped += 1
                continue

            text = node.get("text")
            if not isinstance(text, str) or not text.strip():
                skipped += 1
                continue

            chunks = chunk_text(text, max_chars=args.max_chars)
            if not chunks:
                skipped += 1
                continue

            project_id = node.get("scope")
            node_type = node.get("type")
            ts = node.get("ts")

            if args.project_id and str(project_id) != str(args.project_id):
                skipped += 1
                continue

            meta = node.get("meta") or {}
            session_id = None
            entity_id = None
            source_path = None
            if isinstance(meta, dict):
                session_id = meta.get("session_id") or meta.get("session")
                entity_id = meta.get("entity_id") or meta.get("desk_id") or meta.get("agent_id")
                source_path = meta.get("source_path") or meta.get("path") or meta.get("artifact_id")

            # Deterministic provenance fallback: if the node doesn't declare a source_path,
            # treat the ledger as the source (anchorable via node_id).
            if not source_path:
                source_path = str((Path(args.nodes).expanduser()).resolve()) + f"#{node_id}"
            meta_json = None
            if meta is not None:
                try:
                    meta_json = json.dumps(meta, ensure_ascii=False)
                except Exception:
                    meta_json = None

            # Replace chunks for this node (keeps DB consistent with latest rebuild)
            cur.execute("DELETE FROM chunks WHERE node_id=?", (node_id,))
            cur.execute("DELETE FROM chunks_fts WHERE node_id=?", (node_id,))

            vectors = None
            model_name = None
            if embedder is not None:
                res = embedder.embed_texts(chunks)
                vectors = res.vectors
                model_name = res.model

            for idx, ch in enumerate(chunks):
                chunk_id = f"c{idx:03d}"

                emb_blob = None
                emb_int8_blob = None
                if vectors is not None:
                    # float32 little-endian
                    import array

                    arr = array.array("f", [float(x) for x in vectors[idx]])
                    # Ensure little-endian on disk
                    if arr.itemsize != 4:
                        raise RuntimeError("Unexpected float size")
                    emb_blob = arr.tobytes()

                    # Quantize to int8 if requested
                    if args.quantize:
                        from memory_system.embeddings.quantize import quantize_int8
                        emb_int8_blob = quantize_int8(vectors[idx])

                backend_name = None
                if embedder is not None:
                    backend_name = args.backend

                cur.execute(
                    """
                    INSERT OR REPLACE INTO chunks(
                      node_id, chunk_id,
                      project_id, session_id, entity_id,
                      node_type, source_path,
                      ts,
                      text, text_sha256,
                      meta_json,
                      embedding, embedding_int8, embedding_model, embedding_backend,
                      created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        node_id,
                        chunk_id,
                        str(project_id) if project_id is not None else None,
                        str(session_id) if session_id is not None else None,
                        str(entity_id) if entity_id is not None else None,
                        str(node_type) if node_type is not None else None,
                        str(source_path) if source_path is not None else None,
                        str(ts) if ts is not None else None,
                        ch,
                        sha256_text(ch),
                        meta_json,
                        emb_blob,
                        emb_int8_blob,
                        model_name,
                        backend_name,
                        iso_now(),
                    ),
                )

                # Keep FTS in sync
                cur.execute(
                    """
                    INSERT INTO chunks_fts(node_id, chunk_id, project_id, node_type, text)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        node_id,
                        chunk_id,
                        str(project_id) if project_id is not None else "",
                        str(node_type) if node_type is not None else "",
                        ch,
                    ),
                )

                inserted += 1

        conn.commit()

        print(
            f"Indexed {inserted} chunks into {db_path} (skipped_nodes={skipped})."
        )

        # Build FAISS index if requested
        if args.build_faiss:
            faiss_path = db_path.with_suffix(".faiss")
            build_faiss_index(conn, faiss_path)

        # Build keyword index if requested
        if args.build_keywords:
            from memory_system.tools.build_keyword_index import build_index
            kw_out = db_path.parent / "keyword_index.json"
            kw_data = build_index(nodes_path)
            n_words = len([k for k in kw_data if k != "_nodes"])
            n_nodes = len(kw_data.get("_nodes", {}))
            with kw_out.open("w", encoding="utf-8") as kf:
                json.dump(kw_data, kf, ensure_ascii=False)
            print(f"Built keyword index: {n_words} words, {n_nodes} nodes -> {kw_out}")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Incremental delta indexer for memory embeddings.

Processes the write-ahead log (wal.jsonl) and applies changes to embeddings.sqlite
without requiring a full rebuild.

WAL format:
    {"op": "add", "node_id": "rule:xyz", "text": "...", "ts": "..."}
    {"op": "delete", "node_id": "rule:xyz"}
    {"op": "update", "node_id": "rule:xyz", "text": "...", "ts": "..."}

Usage:
    python delta_index.py              # Process WAL and update index
    python delta_index.py --dry-run    # Show what would be done
    python delta_index.py --clear-wal  # Clear WAL after processing
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow importing memory_system as a package
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from memory_system.paths import default_embeddings_db_path, default_nodes_path, default_wal_path


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_wal(wal_path: Path) -> List[Dict[str, Any]]:
    """Load and parse WAL entries."""
    if not wal_path.exists():
        return []

    entries = []
    for line in wal_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict) and "op" in entry and "node_id" in entry:
                entries.append(entry)
        except json.JSONDecodeError:
            continue

    return entries


def get_node_from_ledger(node_id: str, nodes_path: Path) -> Optional[Dict[str, Any]]:
    """Fetch full node data from nodes.jsonl."""
    if not nodes_path.exists():
        return None

    for line in nodes_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            node = json.loads(line)
            if isinstance(node, dict) and node.get("id") == node_id:
                return node
        except json.JSONDecodeError:
            continue

    return None


def chunk_text(text: str, max_chars: int = 800) -> List[str]:
    """Simple chunker matching embed_index.py logic."""
    t = (text or "").strip()
    if not t:
        return []

    if len(t) <= max_chars:
        return [t]

    # Split on paragraphs
    paras = [p.strip() for p in t.split("\n\n") if p.strip()]
    chunks = []
    buf = ""

    for p in paras:
        candidate = (buf + "\n\n" + p).strip() if buf else p
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            buf = p if len(p) <= max_chars else p[:max_chars]

    if buf:
        chunks.append(buf)

    return chunks


def apply_add(
    conn: sqlite3.Connection,
    node_id: str,
    text: str,
    ts: str,
    embedder,
    nodes_path: Path,
) -> int:
    """Add or update a node's embeddings."""
    # Get full node data for metadata
    node = get_node_from_ledger(node_id, nodes_path)
    if node is None:
        # Minimal node from WAL
        node = {"id": node_id, "text": text, "ts": ts}

    text = node.get("text") or text
    chunks = chunk_text(text)
    if not chunks:
        return 0

    cur = conn.cursor()

    # Delete existing chunks for this node
    cur.execute("DELETE FROM chunks WHERE node_id = ?", (node_id,))
    cur.execute("DELETE FROM chunks_fts WHERE node_id = ?", (node_id,))

    # Compute embeddings
    vectors = None
    model_name = None
    if embedder is not None:
        result = embedder.embed_texts(chunks)
        vectors = result.vectors
        model_name = result.model

    project_id = node.get("scope")
    node_type = node.get("type")
    meta = node.get("meta") or {}
    session_id = meta.get("session_id") if isinstance(meta, dict) else None
    entity_id = meta.get("entity_id") if isinstance(meta, dict) else None
    source_path = meta.get("source_path") if isinstance(meta, dict) else None

    import hashlib

    inserted = 0
    for idx, chunk in enumerate(chunks):
        chunk_id = f"c{idx:03d}"
        text_sha256 = hashlib.sha256(chunk.encode("utf-8")).hexdigest()

        emb_blob = None
        if vectors is not None:
            import array
            arr = array.array("f", [float(x) for x in vectors[idx]])
            emb_blob = arr.tobytes()

        cur.execute(
            """
            INSERT OR REPLACE INTO chunks(
                node_id, chunk_id, project_id, session_id, entity_id,
                node_type, source_path, ts, text, text_sha256,
                meta_json, embedding, embedding_model, embedding_backend, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                chunk_id,
                str(project_id) if project_id else None,
                str(session_id) if session_id else None,
                str(entity_id) if entity_id else None,
                str(node_type) if node_type else None,
                str(source_path) if source_path else None,
                str(ts) if ts else None,
                chunk,
                text_sha256,
                json.dumps(meta) if meta else None,
                emb_blob,
                model_name,
                "fastembed" if embedder else None,
                iso_now(),
            ),
        )

        # Update FTS
        cur.execute(
            """
            INSERT INTO chunks_fts(node_id, chunk_id, project_id, node_type, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                node_id,
                chunk_id,
                str(project_id) if project_id else "",
                str(node_type) if node_type else "",
                chunk,
            ),
        )

        inserted += 1

    return inserted


def apply_delete(conn: sqlite3.Connection, node_id: str) -> int:
    """Delete a node's embeddings."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chunks WHERE node_id = ?", (node_id,))
    count = cur.fetchone()[0]

    cur.execute("DELETE FROM chunks WHERE node_id = ?", (node_id,))
    cur.execute("DELETE FROM chunks_fts WHERE node_id = ?", (node_id,))

    return count


def process_wal(
    wal_path: Path,
    db_path: Path,
    nodes_path: Path,
    dry_run: bool = False,
    clear_wal: bool = False,
    backend: str = "fastembed",
    model: str = "BAAI/bge-small-en-v1.5",
) -> Dict[str, int]:
    """Process WAL entries and apply to database."""
    entries = load_wal(wal_path)
    if not entries:
        print("WAL is empty, nothing to process.")
        return {"added": 0, "deleted": 0, "updated": 0, "chunks": 0}

    print(f"Found {len(entries)} WAL entries to process")

    if dry_run:
        for entry in entries:
            print(f"  {entry['op']}: {entry['node_id']}")
        return {"added": 0, "deleted": 0, "updated": 0, "chunks": 0}

    # Load embedder
    embedder = None
    if db_path.exists():
        try:
            from memory_system.embeddings.factory import get_embedder
            embedder = get_embedder(backend, model=model, use_cache=True)
            print(f"Loaded embedder: {embedder.model_name}")
        except Exception as e:
            print(f"Warning: Could not load embedder: {e}")

    conn = sqlite3.connect(str(db_path))
    stats = {"added": 0, "deleted": 0, "updated": 0, "chunks": 0}

    try:
        for entry in entries:
            op = entry.get("op")
            node_id = entry.get("node_id")

            if op == "add":
                chunks = apply_add(
                    conn,
                    node_id,
                    entry.get("text", ""),
                    entry.get("ts", ""),
                    embedder,
                    nodes_path,
                )
                stats["added"] += 1
                stats["chunks"] += chunks
                print(f"  ADD {node_id}: {chunks} chunks")

            elif op == "delete":
                deleted = apply_delete(conn, node_id)
                stats["deleted"] += 1
                print(f"  DELETE {node_id}: {deleted} chunks removed")

            elif op == "update":
                # Update = delete + add
                apply_delete(conn, node_id)
                chunks = apply_add(
                    conn,
                    node_id,
                    entry.get("text", ""),
                    entry.get("ts", ""),
                    embedder,
                    nodes_path,
                )
                stats["updated"] += 1
                stats["chunks"] += chunks
                print(f"  UPDATE {node_id}: {chunks} chunks")

        conn.commit()

        # Clear WAL if requested
        if clear_wal and wal_path.exists():
            wal_path.unlink()
            print("WAL cleared.")

    finally:
        conn.close()

    print(f"\nDelta index complete: {stats}")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental delta indexer")
    parser.add_argument(
        "--wal",
        type=Path,
        default=default_wal_path(),
        help="Path to WAL file",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=default_embeddings_db_path(),
        help="Path to embeddings database",
    )
    parser.add_argument(
        "--nodes",
        type=Path,
        default=default_nodes_path(),
        help="Path to nodes.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--clear-wal",
        action="store_true",
        help="Clear WAL after successful processing",
    )
    parser.add_argument("--backend", default="fastembed", help="Embedder backend")
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5", help="Embedding model")

    args = parser.parse_args()

    process_wal(
        wal_path=args.wal.expanduser(),
        db_path=args.db.expanduser(),
        nodes_path=args.nodes.expanduser(),
        dry_run=args.dry_run,
        clear_wal=args.clear_wal,
        backend=args.backend,
        model=args.model,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

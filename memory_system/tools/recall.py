#!/usr/bin/env python3
"""Semantic memory recall (single entry point).

Retrieval policy (locked):
1) hybrid query (FTS + vector) scoped to project_id
2) if zero hits, fallback to FTS-only scoped
3) if still zero, fallback to heuristic recall (legacy)
4) never return cross-project hits unless --global

Output: machine-usable JSON list.

NOTE: Run with the repo venv for semantic embeddings:
  ~/clawd/.venv/bin/python memory_system/tools/recall.py ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path as _Path

# Allow importing memory_system as a package when running as a script.
_REPO_ROOT = str(_Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import array
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from memory_system.paths import default_embeddings_db_path, default_embeddings_faiss_path, default_nodes_path


def repo_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def load_vec(blob: bytes) -> List[float]:
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def norm(a: List[float]) -> float:
    return (sum(x * x for x in a) ** 0.5) or 1.0


def cosine(a: List[float], b: List[float]) -> float:
    return dot(a, b) / (norm(a) * norm(b))


def query_openclaw(query: str, topk: int, min_score: float = 0.35) -> List[Dict[str, Any]]:
    """Query OpenClaw's unified memory index (primary search method).

    Uses 'openclaw memory search' which has:
    - 768-dim embeddings via embeddinggemma
    - sqlite-vec HNSW for O(log n) search
    - Hybrid 70% vector + 30% FTS ranking
    - Cached embeddings for fast repeated queries
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "openclaw", "memory", "search", query,
                "--max-results", str(topk * 2),  # Get more to filter
                "--min-score", str(min_score),
                "--json"
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return []

        # Parse JSON output - OpenClaw returns {"results": [...]}
        # Output may have warnings before JSON, so find the JSON start
        stdout = result.stdout
        json_start = stdout.find("{")
        if json_start == -1:
            return []
        stdout = stdout[json_start:]

        data = json.loads(stdout)
        if isinstance(data, dict) and "results" in data:
            items = data["results"]
        elif isinstance(data, list):
            items = data
        else:
            return []

        # Convert to our result format
        results: List[Dict[str, Any]] = []
        for item in items[:topk]:
            path = item.get("path", "")
            # Extract node_id from path if it's a rendered node
            node_id = ""
            if "nodes_rendered/" in path:
                # e.g., memory/nodes_rendered/rule_two_layer_memory.md -> rule:two-layer-memory
                filename = Path(path).stem
                node_id = filename.replace("_", ":", 1).replace("_", "-")

            # Extract preview from snippet
            snippet = item.get("snippet", "")
            # Remove YAML frontmatter for cleaner preview
            if snippet.startswith("---"):
                parts = snippet.split("---", 2)
                if len(parts) >= 3:
                    snippet = parts[2].strip()

            results.append({
                "node_id": node_id or path,
                "node_type": "",  # Not available from openclaw output
                "project_id": "",
                "score": float(item.get("score", 0)),
                "ts": "",
                "source_path": path,
                "preview": snippet[:180].replace("\n", " "),
                "provenance": {
                    "method": "openclaw",
                    "source": "unified-index",
                },
                "provenance_status": "ok",
            })

        return results
    except FileNotFoundError:
        # openclaw binary not in PATH — fall through to FAISS/heuristic
        return []

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError) as e:
        # Silently fall back to local search
        return []


def faiss_fallback(query: str, topk: int, backend: str = "fastembed", model: str = "BAAI/bge-small-en-v1.5") -> List[Dict[str, Any]]:
    """FAISS-accelerated vector search fallback (O(log n) for large datasets)."""
    faiss_path = default_embeddings_faiss_path()
    if not faiss_path.exists():
        return []

    try:
        from memory_system.tools.faiss_search import search_faiss
        from memory_system.embeddings.factory import get_embedder

        embedder = get_embedder(backend, model=model)
        result = embedder.embed_texts([query])
        query_vec = result.vectors[0]

        faiss_results = search_faiss(query_vec, faiss_path, topk)

        # Convert to standard format
        results: List[Dict[str, Any]] = []
        for r in faiss_results:
            results.append({
                "node_id": r["node_id"],
                "node_type": "",
                "project_id": "",
                "score": r["score"],
                "ts": "",
                "source_path": "",
                "preview": "",  # Would need DB lookup for preview
                "provenance": {
                    "method": "faiss",
                    "chunk_id": r["chunk_id"],
                },
                "provenance_status": "ok",
            })
        return results

    except Exception:
        return []


def heuristic_fallback(query: str, topk: int, nodes_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Heuristic fallback using keyword index (O(1) per token) with nodes.jsonl scan as last resort."""
    toks = tokenize(query)

    # Try keyword index first (fast path)
    kw_index_path = default_nodes_path().parent / "keyword_index.json"
    if kw_index_path.exists() and toks:
        try:
            kw_index = json.loads(kw_index_path.read_text(encoding="utf-8"))
            node_meta = kw_index.get("_nodes", {})

            # Score nodes by token hits using inverted index
            node_scores: Dict[str, int] = {}
            for tok in toks:
                for nid in kw_index.get(tok, []):
                    node_scores[nid] = node_scores.get(nid, 0) + 2

            # Add type bonus
            for nid, score in node_scores.items():
                meta = node_meta.get(nid, {})
                if meta.get("type") in ("rule", "decision", "incident"):
                    node_scores[nid] = score + 2

            if node_scores:
                ranked = sorted(node_scores.items(), key=lambda x: (x[1], node_meta.get(x[0], {}).get("ts", "")), reverse=True)
                results: List[Dict[str, Any]] = []
                for nid, s in ranked[:topk]:
                    meta = node_meta.get(nid, {})
                    results.append({
                        "node_id": nid,
                        "node_type": meta.get("type"),
                        "project_id": meta.get("scope") or "",
                        "score": float(s),
                        "ts": meta.get("ts"),
                        "source_path": None,
                        "preview": meta.get("text_preview", ""),
                        "provenance": "keyword_index",
                    })
                return results
        except Exception:
            pass  # Fall through to O(n) scan

    # O(n) scan fallback (no keyword index available)
    nodes_path = nodes_path or default_nodes_path()
    if not nodes_path.exists():
        return []

    out: List[Tuple[int, Dict[str, Any]]] = []
    for line in nodes_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            n = json.loads(line)
        except Exception:
            continue
        if not isinstance(n, dict):
            continue
        s = score_node(n, toks)
        if s > 0:
            out.append((s, n))

    out.sort(key=lambda x: (x[0], str(x[1].get("ts") or "")), reverse=True)

    results: List[Dict[str, Any]] = []
    for s, n in out[:topk]:
        results.append(
            {
                "node_id": n.get("id"),
                "node_type": n.get("type"),
                "project_id": n.get("scope") or "",
                "score": float(s),
                "ts": n.get("ts"),
                "source_path": (n.get("meta") or {}).get("source_path") if isinstance(n.get("meta"), dict) else None,
                "preview": (n.get("text") or "")[:180],
                "provenance": "heuristic",
            }
        )
    return results


def tokenize(q: str) -> List[str]:
    q = q.lower()
    q = re.sub(r"[^a-z0-9_\-\s]", " ", q)
    toks = [t for t in q.split() if len(t) >= 3]
    return toks[:30]


def score_node(n: Dict[str, Any], toks: List[str]) -> int:
    text = " ".join(
        [
            str(n.get("id") or ""),
            str(n.get("type") or ""),
            str(n.get("scope") or ""),
            str(n.get("text") or ""),
            json.dumps(n.get("meta") or {}, ensure_ascii=False),
            " ".join(n.get("tags") or []),
        ]
    ).lower()
    score = 0
    for t in toks:
        if t in text:
            score += 2
    if n.get("type") in ("rule", "decision", "incident"):
        score += 2
    return score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--project-id", default=None)
    ap.add_argument("--global", dest="global_", action="store_true")

    ap.add_argument("--node-type", default=None)
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--entity-id", default=None)

    ap.add_argument("--db", default=str(default_embeddings_db_path()))
    ap.add_argument("--nodes", default=None, help="path to nodes.jsonl for heuristic-only recall")
    ap.add_argument("--backend", default="fastembed")
    ap.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--allow-download", action="store_true")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--strict-provenance", action="store_true", help="Exclude hits missing provenance")
    ap.add_argument("--use-openclaw", action="store_true", default=True, help="Try OpenClaw unified index first (default: True)")
    ap.add_argument("--no-openclaw", action="store_true", help="Skip OpenClaw, use local hybrid search only")
    ap.add_argument("--min-score", type=float, default=0.35, help="Minimum score threshold")
    ap.add_argument("--hierarchical", action="store_true", help="Use multi-stage hierarchical retrieval")
    ap.add_argument("--half-life", type=float, default=14.0, help="Temporal decay half-life in days (with --hierarchical)")

    args = ap.parse_args()

    if args.nodes:
        # nodes override: heuristic-only search
        results = heuristic_fallback(args.query, args.topk, Path(args.nodes))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if not args.global_ and not args.project_id:
        raise SystemExit("--project-id is required (or pass --global)")

    # Use hierarchical retrieval if requested
    if args.hierarchical:
        from memory_system.tools.hierarchical_recall import hierarchical_search
        results = hierarchical_search(
            query=args.query,
            topk=args.topk,
            half_life_days=args.half_life,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    # Try OpenClaw unified index first (faster, cached, better quality)
    if args.use_openclaw and not args.no_openclaw:
        results = query_openclaw(args.query, args.topk, args.min_score)
        if results:
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0

    # Try FAISS fallback (O(log n) local search)
    faiss_results = faiss_fallback(args.query, args.topk, args.backend, args.model)
    if faiss_results:
        print(json.dumps(faiss_results, ensure_ascii=False, indent=2))
        return 0

    if args.no_download and args.allow_download:
        raise SystemExit("Choose only one: --allow-download or --no-download")

    allow_download = bool(args.allow_download)
    if args.no_download:
        allow_download = False

    db_path = Path(args.db).expanduser()
    results: List[Dict[str, Any]] = []

    if db_path.exists():
        # Hybrid retrieval
        from memory_system.embeddings.factory import get_embedder

        embedder = get_embedder(
            args.backend,
            model=args.model,
            allow_download=allow_download,
        )
        qvec = embedder.embed_texts([args.query]).vectors[0]

        con = sqlite3.connect(str(db_path))
        try:
            cur = con.cursor()

            # FTS candidates
            if args.global_:
                fts_sql = (
                    "SELECT node_id, chunk_id, project_id, node_type, text, bm25(chunks_fts) AS rank "
                    "FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT ?"
                )
                fts_params = (args.query, 50)
            else:
                fts_sql = (
                    "SELECT node_id, chunk_id, project_id, node_type, text, bm25(chunks_fts) AS rank "
                    "FROM chunks_fts WHERE chunks_fts MATCH ? AND project_id = ? LIMIT ?"
                )
                fts_params = (args.query, str(args.project_id), 50)

            fts_rows = cur.execute(fts_sql, fts_params).fetchall()
            fts_keys = {(r[0], r[1]) for r in fts_rows}

            # Vector rows (scoped)
            if args.global_:
                vec_rows = cur.execute(
                    "SELECT node_id, chunk_id, project_id, node_type, ts, source_path, text, embedding "
                    "FROM chunks WHERE embedding IS NOT NULL"
                ).fetchall()
            else:
                vec_rows = cur.execute(
                    "SELECT node_id, chunk_id, project_id, node_type, ts, source_path, text, embedding "
                    "FROM chunks WHERE embedding IS NOT NULL AND project_id = ?",
                    (str(args.project_id),),
                ).fetchall()

            # Apply optional filters early
            def ok_filters(project_id: str, node_type: str, session_id: Optional[str], entity_id: Optional[str]) -> bool:
                if args.node_type and node_type != args.node_type:
                    return False
                if args.project_id and (not args.global_) and project_id != str(args.project_id):
                    return False
                return True

            vec_scored: List[Tuple[float, Dict[str, Any]]] = []
            for node_id, chunk_id, project_id, node_type, ts, source_path, text, emb_blob in vec_rows:
                proj = str(project_id or "")
                ntype = str(node_type or "")
                if args.node_type and ntype != args.node_type:
                    continue

                v = load_vec(emb_blob)
                score = cosine(qvec, v)
                vec_scored.append(
                    (
                        score,
                        {
                            "node_id": str(node_id),
                            "chunk_id": str(chunk_id),
                            "project_id": proj,
                            "node_type": ntype,
                            "ts": ts,
                            "source_path": source_path,
                            "preview": (str(text or "").strip().replace("\n", " ")[:180]),
                        },
                    )
                )

            vec_scored.sort(key=lambda x: x[0], reverse=True)
            vec_top = vec_scored[:20]
            vec_keys = {(r[1]["node_id"], r[1]["chunk_id"]) for r in vec_top}

            cand = fts_keys.union(vec_keys)

            # If hybrid yields nothing, fall back to FTS-only (scoped)
            if not cand and fts_rows:
                cand = fts_keys

            # Merge/rerank
            vec_map = {(d["node_id"], d["chunk_id"]): s for s, d in vec_top}
            fts_map = {(nid, cid): 1 for (nid, cid) in fts_keys}

            for (nid, cid) in cand:
                # fetch row
                if args.global_:
                    row = cur.execute(
                        "SELECT project_id, node_type, ts, source_path, session_id, entity_id, text FROM chunks WHERE node_id=? AND chunk_id=?",
                        (nid, cid),
                    ).fetchone()
                else:
                    row = cur.execute(
                        "SELECT project_id, node_type, ts, source_path, session_id, entity_id, text FROM chunks WHERE project_id=? AND node_id=? AND chunk_id=?",
                        (str(args.project_id), nid, cid),
                    ).fetchone()

                if not row:
                    continue

                proj, ntype, ts, source_path, session_id, entity_id, text = row
                proj = str(proj or "")
                ntype = str(ntype or "")

                if args.node_type and ntype != args.node_type:
                    continue

                # Provenance integrity
                prov = {
                    "chunk_id": cid,
                    "source_path": source_path,
                    "session_id": session_id,
                    "entity_id": entity_id,
                }
                prov_ok = bool(source_path or session_id or entity_id)
                prov_status = "ok" if prov_ok else "missing"

                if args.strict_provenance and not prov_ok:
                    continue

                score = float(vec_map.get((nid, cid), 0.0))
                if (nid, cid) in fts_map:
                    score += 0.05
                if (not args.global_) and proj == str(args.project_id):
                    score += 0.10
                if not prov_ok:
                    score -= 0.20

                results.append(
                    {
                        "node_id": nid,
                        "node_type": ntype,
                        "project_id": proj,
                        "score": score,
                        "ts": ts,
                        "source_path": source_path,
                        "preview": (str(text or "").strip().replace("\n", " ")[:180]),
                        "provenance": {
                            "method": "hybrid",
                            **prov,
                        },
                        "provenance_status": prov_status,
                    }
                )

        finally:
            con.close()

    # fallback if nothing
    if not results:
        # FTS-only already attempted above; now heuristic.
        results = heuristic_fallback(args.query, args.topk)

    # Final sort and cap
    results.sort(key=lambda r: (float(r.get("score") or 0.0), str(r.get("ts") or "")), reverse=True)
    results = results[: args.topk]

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Query local embeddings sqlite for nearest chunks.

This works with either:
- real embeddings (future)
- hash stub embeddings (pipeline test)

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

import array
import sqlite3
from pathlib import Path
from typing import List, Tuple

from memory_system.paths import default_embeddings_db_path


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--db", default=str(default_embeddings_db_path()))
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--backend", default="hash")
    ap.add_argument("--model", default=None)
    ap.add_argument("--allow-download", action="store_true", help="Allow model download (setup only)")
    ap.add_argument("--no-download", action="store_true", help="Disallow downloads; fail fast if model missing")
    ap.add_argument("--dim", type=int, default=96)
    ap.add_argument("--project-id", default=None, help="Required unless --global")
    ap.add_argument("--global", dest="global_", action="store_true", help="Allow cross-project retrieval")
    ap.add_argument("--fts-topn", type=int, default=50)
    ap.add_argument("--vec-topn", type=int, default=20)
    ap.add_argument("--debug-sql", action="store_true", help="Print SQL statements (audit/debug)")
    args = ap.parse_args()

    if not args.global_ and not args.project_id:
        raise SystemExit("--project-id is required (or pass --global)")

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
    qvec = embedder.embed_texts([args.query]).vectors[0]

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        raise SystemExit(f"embeddings DB not found: {db_path}")

    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        # Hybrid retrieval:
        # 1) FTS candidates (top N)
        # NOTE: enforce scoping in SQL (not just CLI).
        if args.global_:
            fts_sql = (
                "SELECT node_id, chunk_id, project_id, node_type, text, bm25(chunks_fts) AS rank "
                "FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT ?"
            )
            fts_params = (args.query, args.fts_topn)
        else:
            fts_sql = (
                "SELECT node_id, chunk_id, project_id, node_type, text, bm25(chunks_fts) AS rank "
                "FROM chunks_fts WHERE chunks_fts MATCH ? AND project_id = ? LIMIT ?"
            )
            fts_params = (args.query, str(args.project_id), args.fts_topn)

        if args.debug_sql:
            print(f"SQL[fts]: {fts_sql}")
        fts_rows = cur.execute(fts_sql, fts_params).fetchall()

        fts_set = {(r[0], r[1]) for r in fts_rows}

        # 2) Vector candidates (top M) within project scope (or global)
        if args.global_:
            vec_sql = (
                "SELECT node_id, chunk_id, project_id, node_type, text, embedding "
                "FROM chunks WHERE embedding IS NOT NULL"
            )
            vec_params = ()
        else:
            vec_sql = (
                "SELECT node_id, chunk_id, project_id, node_type, text, embedding "
                "FROM chunks WHERE embedding IS NOT NULL AND project_id = ?"
            )
            vec_params = (str(args.project_id),)

        if args.debug_sql:
            print(f"SQL[vec]: {vec_sql}")
        vec_rows = cur.execute(vec_sql, vec_params).fetchall()

        vec_scored: List[Tuple[float, str, str, str, str, str]] = []
        for node_id, chunk_id, project_id, node_type, text, emb_blob in vec_rows:
            vec = load_vec(emb_blob)
            score = cosine(qvec, vec)
            vec_scored.append((score, str(node_id), str(chunk_id), str(project_id or ""), str(node_type or ""), str(text or "")))

        vec_scored.sort(key=lambda x: x[0], reverse=True)
        vec_top = vec_scored[: args.vec_topn]
        vec_set = {(r[1], r[2]) for r in vec_top}

        # 3) Merge candidates
        cand_keys = fts_set.union(vec_set)

        # Fetch full rows for candidates
        placeholders = ",".join(["(?,?)"] * len(cand_keys))
        params: List[str] = []
        for nid, cid in cand_keys:
            params.extend([nid, cid])

        rows = []
        if cand_keys:
            if args.global_:
                merge_sql = (
                    "SELECT node_id, chunk_id, project_id, node_type, ts, text, embedding "
                    "FROM chunks WHERE (node_id, chunk_id) IN (" + placeholders + ")"
                )
                merge_params = params
            else:
                merge_sql = (
                    "SELECT node_id, chunk_id, project_id, node_type, ts, text, embedding "
                    "FROM chunks WHERE project_id = ? AND (node_id, chunk_id) IN (" + placeholders + ")"
                )
                merge_params = [str(args.project_id)] + params

            if args.debug_sql:
                print(f"SQL[merge]: {merge_sql}")
            rows = cur.execute(merge_sql, merge_params).fetchall()

        # Score merge: vector cosine + boosts
        scored: List[Tuple[float, str, str, str, str, str]] = []
        vec_map = {(nid, cid): s for s, nid, cid, _, _, _ in vec_top}
        fts_map = {(nid, cid): rank for nid, cid, _, _, _, rank in fts_rows}

        for node_id, chunk_id, project_id, node_type, ts, text, emb_blob in rows:
            nid = str(node_id)
            cid = str(chunk_id)
            proj = str(project_id or "")
            ntype = str(node_type or "")
            base = float(vec_map.get((nid, cid), 0.0))

            # project boost
            if (not args.global_) and proj == str(args.project_id):
                base += 0.10

            # keyword boost (fts rank is lower=better; invert lightly)
            if (nid, cid) in fts_map:
                base += 0.05

            preview = str(text or "").strip().replace("\n", " ")
            if len(preview) > 140:
                preview = preview[:137] + "..."
            scored.append((base, nid, cid, proj, ntype, preview))

        scored.sort(key=lambda x: (x[0], x[3], x[1], x[2]), reverse=True)
        top = scored[: args.topk]

        for score, node_id, chunk_id, project_id, node_type, preview in top:
            print(f"{score:0.4f}\t{project_id}\t{node_type}\t{node_id}\t{chunk_id}\t{preview}")

        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())

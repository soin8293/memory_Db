#!/usr/bin/env python3
"""FAISS-accelerated vector search for memory recall.

Provides O(log n) approximate nearest neighbor search using FAISS IVF index.
Falls back to exact search for small datasets or when IVF not available.

Usage:
    python3 faiss_search.py --query "search text" --topk 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow importing memory_system as a package
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from memory_system.paths import default_embeddings_faiss_path


def load_faiss_index(index_path: Path) -> Tuple[Any, List[str]]:
    """Load FAISS index and ID mapping.

    Returns:
        (faiss_index, id_list) where id_list[i] = "node_id:chunk_id"
    """
    try:
        import faiss
    except ImportError:
        raise RuntimeError("FAISS not installed. Run: pip install faiss-cpu")

    if not index_path.exists():
        raise FileNotFoundError(f"FAISS index not found: {index_path}")

    ids_path = index_path.with_suffix(".ids.json")
    if not ids_path.exists():
        raise FileNotFoundError(f"ID mapping not found: {ids_path}")

    index = faiss.read_index(str(index_path))
    with ids_path.open("r") as f:
        ids = json.load(f)

    return index, ids


def search_faiss(
    query_vec: List[float],
    index_path: Path,
    topk: int = 10,
) -> List[Dict[str, Any]]:
    """Search FAISS index for similar vectors.

    Args:
        query_vec: Query embedding vector
        index_path: Path to FAISS index file
        topk: Number of results to return

    Returns:
        List of dicts with node_id, chunk_id, score
    """
    try:
        import faiss
        import numpy as np
    except ImportError:
        raise RuntimeError("FAISS not installed. Run: pip install faiss-cpu")

    index, ids = load_faiss_index(index_path)

    # Prepare query vector
    query_np = np.array([query_vec], dtype="float32")
    faiss.normalize_L2(query_np)  # Normalize for cosine similarity

    # Search
    scores, indices = index.search(query_np, min(topk, index.ntotal))

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(ids):
            continue  # Invalid index

        id_str = ids[idx]
        if ":" in id_str:
            node_id, chunk_id = id_str.rsplit(":", 1)
        else:
            node_id = id_str
            chunk_id = ""

        results.append({
            "node_id": node_id,
            "chunk_id": chunk_id,
            "score": float(score),
            "faiss_index": int(idx),
        })

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Search FAISS index")
    parser.add_argument("--query", required=True, help="Query text")
    parser.add_argument("--topk", type=int, default=10, help="Number of results")
    parser.add_argument(
        "--index",
        type=Path,
        default=default_embeddings_faiss_path(),
        help="Path to FAISS index",
    )
    parser.add_argument(
        "--backend",
        default="fastembed",
        help="Embedder backend (fastembed|hash)",
    )
    parser.add_argument(
        "--model",
        default="BAAI/bge-small-en-v1.5",
        help="Embedding model",
    )

    args = parser.parse_args()

    # Get query embedding
    from memory_system.embeddings.factory import get_embedder

    embedder = get_embedder(args.backend, model=args.model)
    result = embedder.embed_texts([args.query])
    query_vec = result.vectors[0]

    # Search FAISS
    try:
        results = search_faiss(query_vec, args.index.expanduser(), args.topk)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run embed_index.py with --embed --build-faiss first.", file=sys.stderr)
        return 1

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

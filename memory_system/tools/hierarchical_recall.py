#!/usr/bin/env python3
"""Hierarchical multi-stage memory retrieval.

Improves recall quality through:
1. Coarse search over summaries (high-level context)
2. Fine search over source chunks of top matches
3. Temporal decay to prefer recent memories

Usage:
    python hierarchical_recall.py --query "job application" --topk 8
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow importing memory_system as a package
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def parse_iso_ts(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp to datetime."""
    if not ts:
        return None
    try:
        # Handle various ISO formats
        ts = ts.replace("Z", "+00:00")
        if "+" not in ts and "-" not in ts[10:]:
            ts = ts + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def temporal_decay(base_score: float, ts: str, half_life_days: float = 14.0) -> float:
    """Apply temporal decay to score.

    Formula: score *= 0.5 + 0.5 * exp(-0.693 * age_days / half_life)

    This gives:
    - Today: 100% of score
    - 14 days ago: 75% of score
    - 28 days ago: 62.5% of score
    - 56 days ago: 56.25% of score

    The 0.5 floor ensures old memories aren't completely forgotten.
    """
    parsed = parse_iso_ts(ts)
    if parsed is None:
        return base_score

    now = datetime.now(parsed.tzinfo)
    age_days = max(0, (now - parsed).days)

    # Exponential decay with floor
    decay = 0.5 + 0.5 * math.exp(-0.693 * age_days / half_life_days)
    return base_score * decay


def search_summaries(
    query: str,
    topk: int = 20,
    min_score: float = 0.3,
) -> List[Dict[str, Any]]:
    """Stage 1: Coarse search over summaries."""
    from memory_system.tools.recall import query_openclaw

    # OpenClaw indexes summaries in memory_system/data/summaries/
    results = query_openclaw(query, topk * 2, min_score)

    # Filter to summary files only
    summaries = []
    for r in results:
        path = r.get("source_path", "")
        if "summaries" in path or r.get("node_type") == "summary":
            summaries.append(r)

    return summaries[:topk]


def search_chunks(
    query: str,
    topk: int = 10,
    source_filter: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Stage 2: Fine search over source chunks."""
    from memory_system.tools.recall import faiss_fallback, heuristic_fallback

    # Try FAISS first for speed
    results = faiss_fallback(query, topk * 3)
    if not results:
        results = heuristic_fallback(query, topk * 3)

    # Filter to source documents if provided
    if source_filter:
        filtered = []
        for r in results:
            node_id = r.get("node_id", "")
            # Match if node_id is in any of the source filters
            for sf in source_filter:
                if sf in node_id or node_id in sf:
                    filtered.append(r)
                    break
        results = filtered

    return results[:topk]


def hierarchical_search(
    query: str,
    topk: int = 8,
    summary_topk: int = 5,
    half_life_days: float = 14.0,
    apply_decay: bool = True,
) -> List[Dict[str, Any]]:
    """Multi-stage hierarchical retrieval.

    Stage 1: Search summaries for high-level context (coarse)
    Stage 2: Search source chunks of top summaries (fine)
    Stage 3: Apply temporal decay and merge results
    """
    # Stage 1: Coarse search over summaries
    summaries = search_summaries(query, topk=summary_topk * 2)

    # Extract source references from summaries
    source_refs = []
    for s in summaries[:summary_topk]:
        # Try to extract source node IDs from preview/metadata
        preview = s.get("preview", "")
        node_id = s.get("node_id", "")
        if node_id:
            # Use the summary's node_id prefix as a filter
            prefix = node_id.split(":")[0] if ":" in node_id else node_id
            source_refs.append(prefix)

    # Stage 2: Fine search over chunks (filtered by summaries if available)
    chunks = search_chunks(
        query,
        topk=topk * 2,
        source_filter=source_refs if source_refs else None,
    )

    # Stage 3: Merge and apply temporal decay
    seen_nodes = set()
    results: List[Dict[str, Any]] = []

    # Add summary results first (they provide context)
    for r in summaries:
        node_id = r.get("node_id", "")
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)

        score = float(r.get("score", 0))
        if apply_decay:
            score = temporal_decay(score, r.get("ts", ""), half_life_days)

        results.append({
            **r,
            "score": score,
            "stage": "summary",
        })

    # Add chunk results
    for r in chunks:
        node_id = r.get("node_id", "")
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)

        score = float(r.get("score", 0))
        if apply_decay:
            score = temporal_decay(score, r.get("ts", ""), half_life_days)

        results.append({
            **r,
            "score": score,
            "stage": "chunk",
        })

    # Sort by score and return top-k
    results.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
    return results[:topk]


def main() -> int:
    parser = argparse.ArgumentParser(description="Hierarchical memory retrieval")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--topk", type=int, default=8, help="Number of results")
    parser.add_argument(
        "--summary-topk",
        type=int,
        default=5,
        help="Number of summaries to use for context",
    )
    parser.add_argument(
        "--half-life",
        type=float,
        default=14.0,
        help="Temporal decay half-life in days",
    )
    parser.add_argument(
        "--no-decay",
        action="store_true",
        help="Disable temporal decay",
    )

    args = parser.parse_args()

    results = hierarchical_search(
        query=args.query,
        topk=args.topk,
        summary_topk=args.summary_topk,
        half_life_days=args.half_life,
        apply_decay=not args.no_decay,
    )

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Compare MemoryDB's linear-scan and inverted-index keyword paths."""

from __future__ import annotations

import json
import platform
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from memory_system.memorydb import MemoryDB


def reciprocal_rank(results: list[str], expected_text: str) -> float:
    """Return reciprocal rank for an exact synthetic fixture text."""
    for rank, text in enumerate(results, start=1):
        if text == expected_text:
            return 1.0 / rank
    return 0.0


def percentile(values: list[float], fraction: float) -> float:
    """Return a nearest-rank percentile without external dependencies."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


def _run_mode(db: MemoryDB, queries: list[dict[str, str]], repeats: int) -> dict[str, Any]:
    timings: list[float] = []
    ranks: list[float] = []
    recall_hits = 0
    case_results = []

    for case in queries:
        first_results: list[str] = []
        case_timings = []
        for _ in range(repeats):
            started = time.perf_counter_ns()
            results = db.lookup(case["query"], limit=3)
            case_timings.append((time.perf_counter_ns() - started) / 1_000_000)
            if not first_results:
                first_results = results
        rr = reciprocal_rank(first_results, case["expected_text"])
        ranks.append(rr)
        recall_hits += int(case["expected_text"] in first_results)
        timings.extend(case_timings)
        case_results.append(
            {
                "query": case["query"],
                "reciprocal_rank": rr,
                "retrieved_at_3": case["expected_text"] in first_results,
            }
        )

    return {
        "mean_reciprocal_rank": round(statistics.mean(ranks), 4),
        "recall_at_3": round(recall_hits / len(queries), 4),
        "median_latency_ms": round(statistics.median(timings), 4),
        "p95_latency_ms": round(percentile(timings, 0.95), 4),
        "query_executions": len(queries) * repeats,
        "cases": case_results,
    }


def run_benchmark(fixtures: dict[str, Any], repeats: int = 50) -> dict[str, Any]:
    """Run both keyword paths in an isolated temporary store."""
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Path(temp_dir) / "benchmark-store"
        db = MemoryDB(project="synthetic-benchmark", store_path=str(store))
        db._ensure_project_layout()
        nodes_path = store / "nodes.jsonl"
        nodes_path.write_text(
            "".join(json.dumps(node) + "\n" for node in fixtures["nodes"]),
            encoding="utf-8",
        )

        scan = _run_mode(db, fixtures["queries"], repeats)
        db._rebuild_project_keyword_index()
        indexed = _run_mode(db, fixtures["queries"], repeats)

    return {
        "schema_version": "1.0.0",
        "dataset": "synthetic-agent-memory-v1",
        "node_count": len(fixtures["nodes"]),
        "query_count": len(fixtures["queries"]),
        "repeats_per_query": repeats,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system(),
            "processor": platform.machine(),
        },
        "modes": {"linear_scan": scan, "inverted_index": indexed},
        "semantic_mode": {
            "status": "not_run",
            "reason": "Optional FAISS/FastEmbed dependencies and a pinned model are outside this dependency-free baseline.",
        },
    }

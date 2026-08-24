import json
from pathlib import Path

from benchmarks.retrieval_benchmark import reciprocal_rank, run_benchmark


def test_reciprocal_rank():
    assert reciprocal_rank(["other", "target"], "target") == 0.5
    assert reciprocal_rank(["other"], "target") == 0.0


def test_synthetic_benchmark_retrieves_all_cases():
    root = Path(__file__).parents[2]
    fixtures = json.loads((root / "benchmarks" / "fixtures.json").read_text(encoding="utf-8"))
    result = run_benchmark(fixtures, repeats=1)
    assert result["modes"]["linear_scan"]["recall_at_3"] == 1.0
    assert result["modes"]["inverted_index"]["recall_at_3"] == 1.0
    assert result["semantic_mode"]["status"] == "not_run"

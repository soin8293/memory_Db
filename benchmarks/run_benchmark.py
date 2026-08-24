"""CLI entry point for the synthetic retrieval benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.retrieval_benchmark import run_benchmark  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "retrieval-baseline.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")

    fixtures = json.loads((ROOT / "benchmarks" / "fixtures.json").read_text(encoding="utf-8"))
    result = run_benchmark(fixtures, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "modes"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

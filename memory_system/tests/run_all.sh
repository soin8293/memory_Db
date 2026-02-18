#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PYTHON_BIN:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY="$ROOT/.venv/bin/python"
  else
    PY="$(command -v python3 || true)"
  fi
fi

if [[ -z "$PY" || ! -x "$PY" ]]; then
  echo "Missing python runtime (set PYTHON_BIN or install python3)" >&2
  exit 2
fi

echo "== Python unit tests =="
"$PY" -m unittest discover -s "$ROOT/memory_system/tests" -p "test_*.py" -v

echo "== Shell integration tests =="
bash "$ROOT/memory_system/tests/test_memory_ops.sh"
bash "$ROOT/memory_system/tests/test_scope_leak.sh"

echo "All tests passed."

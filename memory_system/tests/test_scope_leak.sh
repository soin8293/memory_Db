#!/usr/bin/env bash
set -euo pipefail

# Regression test: scoped retrieval must not leak across project_id.
# Uses hash backend (deterministic) + FTS + our recall entrypoint.

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

TMP_DIR="${TMP_DIR:-$ROOT/tmp/memory_scope_leak_test}"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

NODES="$TMP_DIR/nodes.jsonl"
DB="$TMP_DIR/embeddings.sqlite"

# Two semantically-unique project IDs (no numeric suffixes)
PROJ_A="memory_scope_a"
PROJ_B="memory_scope_b"

# Same keyword, different payload markers
KW="SCOPE_MARKER"
A_TEXT="$KW SCOPE_MARKER_A"
B_TEXT="$KW SCOPE_MARKER_B"

cat >"$NODES" <<EOF
{"id":"note:test_a","type":"note","ts":"2026-02-02T00:00:00Z","scope":"$PROJ_A","text":"$A_TEXT","meta":{"source_path":"test://a"}}
{"id":"note:test_b","type":"note","ts":"2026-02-02T00:00:01Z","scope":"$PROJ_B","text":"$B_TEXT","meta":{"source_path":"test://b"}}
EOF

# Build index (no real embedding model needed for this regression)
"$PY" "$ROOT/memory_system/tools/embed_index.py" \
  --rebuild \
  --nodes "$NODES" \
  --db "$DB" \
  --embed \
  --backend hash \
  --dim 96 \
  --max-chars 200 \
  >/dev/null

# Assertions
out_a="$($PY "$ROOT/memory_system/tools/recall.py" --query "$KW" --project-id "$PROJ_A" --db "$DB" --backend hash --topk 10 --no-openclaw)"
out_b="$($PY "$ROOT/memory_system/tools/recall.py" --query "$KW" --project-id "$PROJ_B" --db "$DB" --backend hash --topk 10 --no-openclaw)"
out_g="$($PY "$ROOT/memory_system/tools/recall.py" --query "$KW" --global --db "$DB" --backend hash --topk 10 --no-openclaw)"

python3 - <<PY
import json, sys

def has_marker(blob, marker):
    for r in blob:
        if marker in (r.get('preview') or ''):
            return True
    return False

a=json.loads("""$out_a""")
b=json.loads("""$out_b""")
g=json.loads("""$out_g""")

assert has_marker(a, "SCOPE_MARKER_A"), "A missing marker A"
assert not has_marker(a, "SCOPE_MARKER_B"), "A leaked marker B"

assert has_marker(b, "SCOPE_MARKER_B"), "B missing marker B"
assert not has_marker(b, "SCOPE_MARKER_A"), "B leaked marker A"

assert has_marker(g, "SCOPE_MARKER_A"), "Global missing marker A"
assert has_marker(g, "SCOPE_MARKER_B"), "Global missing marker B"

print("OK")
PY

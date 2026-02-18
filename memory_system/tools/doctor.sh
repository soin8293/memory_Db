#!/usr/bin/env bash
set -euo pipefail

WORKDIR="$(cd "$(dirname "$0")/../.." && pwd)"
export WORKDIR
CONFIG_FILE="$WORKDIR/memory_system/config.json"

say() { printf "%s\n" "$*"; }

say "# memory_system doctor"
say
say "- ts: $(date -Iseconds)"
say "- workdir: $WORKDIR"

# Check shims
say "\n## Shims"
for p in \
  memory_system/tools \
  memory_system/policy \
  memory_system/projects \
  memory_system/data/summaries \
  memory_system/data/LAST_CHECKPOINT.md
do
  if [[ -e "$WORKDIR/$p" ]]; then
    say "OK: $p -> $(readlink "$WORKDIR/$p" 2>/dev/null || echo '(not symlink)')"
  else
    say "MISSING: $p"
  fi
done

# Check config
say "\n## Config"
if [[ -f "$CONFIG_FILE" ]]; then
  say "OK: config.json present: $CONFIG_FILE"
else
  say "MISSING: config.json: $CONFIG_FILE"
fi

# Check session roots + newest session file
say "\n## Session roots"
if command -v python3 >/dev/null 2>&1 && [[ -f "$CONFIG_FILE" ]]; then
  roots=( )
  while IFS= read -r line; do
    [[ -n "$line" ]] && roots+=("$line")
  done < <(python3 - "$CONFIG_FILE" <<'PY'
import json, pathlib, sys
obj=json.loads(pathlib.Path(sys.argv[1]).expanduser().read_text())
roots=obj.get('sessionRoots') or []
roots=[str(pathlib.Path(r).expanduser()) for r in roots]
print("\n".join([r for r in roots if r]))
PY
  )
else
  roots=(
    "$HOME/.openclaw/agents/main/sessions"
    "$HOME/.clawdbot/agents/main/sessions"
    "$HOME/.codex/sessions"
    "$HOME/.codex/agents/main/sessions"
    "$HOME/.claude/sessions"
    "$HOME/.claude/agents/main/sessions"
    "$HOME/.claude/projects"
  )
fi

# Optional explicit override (colon-separated roots).
if [[ -n "${MEMORY_SESSION_ROOTS:-}" ]]; then
  roots=()
  while IFS= read -r root; do
    expanded="${root/#\~/$HOME}"
    [[ -n "$expanded" ]] && roots+=("$expanded")
  done < <(printf '%s\n' "${MEMORY_SESSION_ROOTS}" | tr ':' '\n')
fi

newest=""
for r in "${roots[@]}"; do
  if [[ -d "$r" ]]; then
    cand="$(ls -t "$r"/*.jsonl 2>/dev/null | grep -vE 'sessions\.jsonl$' | head -n 1 || true)"
    say "OK: root exists: $r (newest: ${cand:-none})"
    [[ -z "$newest" && -n "$cand" ]] && newest="$cand"
  else
    say "MISSING: root: $r"
  fi
done

# Check last checkpoint
say "\n## Last checkpoint"
if [[ -f "$WORKDIR/memory_system/data/LAST_CHECKPOINT.md" ]]; then
  say "OK: memory_system/data/LAST_CHECKPOINT.md"
  sed -n '1,20p' "$WORKDIR/memory_system/data/LAST_CHECKPOINT.md" | sed 's/^/  /'
else
  say "MISSING: memory_system/data/LAST_CHECKPOINT.md"
fi

# Write access
say "\n## Write access"
mkdir -p "$WORKDIR/memory_system/data/summaries" 2>/dev/null || true
if touch "$WORKDIR/memory_system/data/.doctor_write_test" 2>/dev/null; then
  rm -f "$WORKDIR/memory_system/data/.doctor_write_test" || true
  say "OK: can write to memory_system/data/"
else
  say "FAIL: cannot write to memory_system/data/"
fi

say "\n## Checkpoint dry-run"
if "$WORKDIR/memory_system/tools/auto_checkpoint.sh" >/dev/null 2>&1; then
  say "OK: auto_checkpoint.sh succeeded"
else
  say "FAIL: auto_checkpoint.sh failed"
fi

say "\n## Python runtime"
if [[ -x "$WORKDIR/.venv/bin/python" ]]; then
  say "OK: venv python: $WORKDIR/.venv/bin/python"
  "$WORKDIR/.venv/bin/python" -V | sed 's/^/  /'
else
  say "WARN: venv python missing: $WORKDIR/.venv/bin/python"
fi

say "\n## No-network lint (quick)"
# crude grep: flag obvious networking libs in memory_system tools
if rg -n "import (requests|httpx)|urllib\.request|socket\.create_connection" "$WORKDIR/memory_system" >/dev/null 2>&1; then
  say "WARN: found possible networking imports in memory_system/ (inspect manually)"
  rg -n "import (requests|httpx)|urllib\.request|socket\.create_connection" "$WORKDIR/memory_system" | sed 's/^/  /'
else
  say "OK: no obvious networking imports detected"
fi

say "\n## Embeddings DB sanity (points back to sources)"
# Cheap deterministic check against production embeddings.sqlite
# - sample N recent rows
# - require node_id + project_id
# - require at least one provenance field (source_path/session_id/entity_id)
# - require source_path points to an allowed root when present
if [[ -x "$WORKDIR/.venv/bin/python" ]]; then
  if "$WORKDIR/.venv/bin/python" - <<'PY'
import os, sqlite3
from pathlib import Path

workdir = Path(os.environ.get('WORKDIR','')).resolve()
db = (workdir / 'memory_system' / 'data' / 'embeddings.sqlite')
if not db.exists():
    raise SystemExit(0)

con = sqlite3.connect(str(db))
cur = con.cursor()
rows = cur.execute(
    "SELECT node_id, chunk_id, project_id, source_path, session_id, entity_id FROM chunks ORDER BY created_at DESC LIMIT 50"
).fetchall()
con.close()

allowed_prefixes = [
    # allow files/dirs under these roots
    str((workdir / 'memory_system' / 'data').resolve()) + os.sep,
    str(Path('~/.openclaw').expanduser().resolve()) + os.sep,
    str(Path('~/.clawdbot').expanduser().resolve()) + os.sep,
    # allow the repo-local shim memory/ as well (some nodes reference shim paths)
    str((workdir / 'memory').resolve()) + os.sep,
    # allow scheme-style pseudo paths
    'doctor://',
    'test://',
]

def ok_source(p: str) -> bool:
    if not p:
        return False
    if any(p.startswith(x) for x in ('doctor://','test://')):
        return True
    # ledger anchor form: /abs/path/to/nodes.jsonl#node_id
    if '#' in p:
        p = p.split('#', 1)[0]
    rp = str(Path(p).expanduser().resolve())
    for pref in allowed_prefixes:
        if pref.endswith(os.sep) and rp.startswith(pref):
            return True
        if not pref.endswith(os.sep) and rp == pref:
            return True
    return False

bad = 0
for node_id, chunk_id, project_id, source_path, session_id, entity_id in rows:
    if not node_id or not project_id:
        bad += 1
        continue
    # Requirements:
    # - node_id + project_id must exist
    # - provenance must exist: (source_path OR session_id OR entity_id)
    # - if source_path exists, it must be under allowed roots
    prov_ok = bool(source_path or session_id or entity_id)
    if not prov_ok:
        bad += 1
        continue
    if source_path and not ok_source(str(source_path)):
        bad += 1

if bad:
    print(f"SANITY_FAIL rows={len(rows)} bad={bad}")
    raise SystemExit(33)
else:
    print(f"SANITY_OK rows={len(rows)}")
PY
  then
    :
  else
    exit 33
  fi
else
  say "WARN: venv missing; skipping embeddings sanity check"
fi

say "\n## Operational lock check (memory-test)"
# 1) scope leak regression
if "$WORKDIR/memory_system/tests/test_scope_leak.sh" >/dev/null 2>&1; then
  say "OK: test_scope_leak.sh"
else
  say "FAIL: test_scope_leak.sh"
  exit 31
fi

# 2) offline + strict provenance recall check (HERMETIC)
# Do NOT depend on any real project data. We seed a tiny local test scope and
# build a temp DB, then query it with --no-download.
if [[ -x "$WORKDIR/.venv/bin/python" ]]; then
  TMPROOT="${TMPDIR:-/tmp}"
  TMP_DIR="$(mktemp -d "${TMPROOT%/}/memory_doctor_scope.XXXXXX")"
  cleanup_tmp() { rm -rf "$TMP_DIR" 2>/dev/null || true; }
  trap cleanup_tmp EXIT

  PROJ="memory_doctor_scope"
  KW="DOCTOR_SCOPE_MARKER"
  NODES="$TMP_DIR/nodes.jsonl"
  DB="$TMP_DIR/embeddings.sqlite"

  cat >"$NODES" <<EOF
{"id":"note:doctor","type":"note","ts":"2026-02-02T00:00:00Z","scope":"$PROJ","text":"$KW This is a hermetic doctor seed.","meta":{"source_path":"doctor://seed"}}
EOF

  # Build embeddings DB using fastembed with downloads disallowed.
  if "$WORKDIR/.venv/bin/python" "$WORKDIR/memory_system/tools/embed_index.py" \
      --rebuild \
      --nodes "$NODES" \
      --db "$DB" \
      --embed \
      --backend fastembed \
      --model BAAI/bge-small-en-v1.5 \
      --no-download \
      --max-chars 200 \
      >/dev/null 2>&1; then
    :
  else
    say "FAIL: embed_index fastembed --no-download (model cache missing?)"
    exit 32
  fi

  if "$WORKDIR/.venv/bin/python" "$WORKDIR/memory_system/tools/recall.py" \
      --query "$KW" \
      --project-id "$PROJ" \
      --db "$DB" \
      --backend fastembed \
      --model BAAI/bge-small-en-v1.5 \
      --no-download \
      --strict-provenance \
      --topk 3 \
      >/dev/null 2>&1; then
    say "OK: recall offline + strict provenance (hermetic)"
  else
    say "FAIL: recall offline + strict provenance (hermetic)"
    exit 33
  fi
else
  say "WARN: venv missing; skipping recall offline check"
fi

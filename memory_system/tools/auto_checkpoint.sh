#!/usr/bin/env bash
set -euo pipefail

# Local-only checkpointing: summarize the most recent OpenClaw main session
# into a stable, searchable markdown file under this workspace.

WORKDIR="$(cd "$(dirname "$0")/../.." && pwd)"   # repo root (…/clawd)
CONFIG_FILE="${WORKDIR}/memory_system/config.json"

# Defaults (overrideable via config.json / MEMORY_SESSION_ROOTS)
OUT_DIR="${WORKDIR}/memory_system/data/summaries"
STATUS_FILE="${WORKDIR}/memory_system/data/LAST_CHECKPOINT.md"
SESSION_ROOTS=(
  "${HOME}/.openclaw/agents/main/sessions"
  "${HOME}/.clawdbot/agents/main/sessions"
  "${HOME}/.codex/sessions"
  "${HOME}/.codex/agents/main/sessions"
  "${HOME}/.claude/sessions"
  "${HOME}/.claude/agents/main/sessions"
  "${HOME}/.claude/projects"
)

# Load config without relying on exported environment variables (cron-safe).
if [[ -f "$CONFIG_FILE" ]] && command -v python3 >/dev/null 2>&1; then
  SESSION_ROOTS=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && SESSION_ROOTS+=("$line")
  done < <(python3 - "$CONFIG_FILE" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]).expanduser()
obj = json.loads(p.read_text())
roots = obj.get('sessionRoots') or []
roots = [str(pathlib.Path(r).expanduser()) for r in roots]
print("\n".join([r for r in roots if r]))
PY
  )

  OUT_DIR="$(python3 - "$CONFIG_FILE" <<'PY'
import json, pathlib, sys
obj = json.loads(pathlib.Path(sys.argv[1]).expanduser().read_text())
out = (obj.get('checkpoint') or {}).get('outDir') or '~/.openclaw/memorydb/data/summaries'
print(str(pathlib.Path(out).expanduser()))
PY
  )"

  STATUS_FILE="$(python3 - "$CONFIG_FILE" <<'PY'
import json, pathlib, sys
obj = json.loads(pathlib.Path(sys.argv[1]).expanduser().read_text())
out = (obj.get('checkpoint') or {}).get('statusFile') or '~/.openclaw/memorydb/data/LAST_CHECKPOINT.md'
print(str(pathlib.Path(out).expanduser()))
PY
  )"
fi

# Optional explicit override (colon-separated roots).
# Example:
#   MEMORY_SESSION_ROOTS="$HOME/.codex/sessions:$HOME/.claude/projects"
if [[ -n "${MEMORY_SESSION_ROOTS:-}" ]]; then
  SESSION_ROOTS=()
  while IFS= read -r root; do
    expanded="${root/#\~/$HOME}"
    [[ -n "$expanded" ]] && SESSION_ROOTS+=("$expanded")
  done < <(printf '%s\n' "${MEMORY_SESSION_ROOTS}" | tr ':' '\n')
fi

mkdir -p "$OUT_DIR"

# Prevent overlapping runs (cron-safe)
LOCK_DIR="${WORKDIR}/memory_system/data/locks"
LOCK_PATH="${LOCK_DIR}/auto_checkpoint.lock"
mkdir -p "$LOCK_DIR"
if ! mkdir "$LOCK_PATH" 2>/dev/null; then
  echo "Checkpoint already running (lock exists): $LOCK_PATH" >&2
  exit 0
fi
trap 'rmdir "$LOCK_PATH" 2>/dev/null || true' EXIT

# Find newest .jsonl session file across all roots
SESSION_FILE=""
for root in "${SESSION_ROOTS[@]}"; do
  [[ -d "$root" ]] || continue
  cand="$(ls -t "$root"/*.jsonl 2>/dev/null | grep -vE 'sessions\.jsonl$' | head -n 1 || true)"
  if [[ -n "$cand" ]] && [[ -f "$cand" ]]; then
    SESSION_FILE="$cand"
    break
  fi
done

if [[ -z "${SESSION_FILE}" || ! -f "${SESSION_FILE}" ]]; then
  echo "No session jsonl found in any root: ${SESSION_ROOTS[*]}" >&2
  exit 2
fi

SESSION_BASENAME="$(basename "$SESSION_FILE")"
OUT_FILE="${OUT_DIR}/${SESSION_BASENAME%.jsonl}.md"

# Compute session file fingerprint (size + mtime) so we only rerun when it changed.
read -r SESSION_BYTES SESSION_MTIME < <(python3 - "$SESSION_FILE" <<'PY'
import os, sys
st = os.stat(sys.argv[1])
print(st.st_size, int(st.st_mtime))
PY
)

# If we already checkpointed this exact session file at the same size/mtime, skip.
if [[ -f "$STATUS_FILE" ]] \
  && grep -q "^- session: ${SESSION_FILE}$" "$STATUS_FILE" \
  && grep -q "^- status: ok$" "$STATUS_FILE" \
  && grep -q "^- session_bytes: ${SESSION_BYTES}$" "$STATUS_FILE" \
  && grep -q "^- session_mtime: ${SESSION_MTIME}$" "$STATUS_FILE"; then
  exit 0
fi

python3 "${WORKDIR}/memory_system/tools/summarize_session_jsonl.py" \
  --in "$SESSION_FILE" \
  --out "$OUT_FILE" \
  --limit-messages 160 \
  --limit-tools 80 \
  --limit-errors 80 \
  --max-text 280

{
  echo "# LAST_CHECKPOINT"
  echo
  echo "- ts: $(date -Iseconds)"
  echo "- session: $SESSION_FILE"
  echo "- session_bytes: $SESSION_BYTES"
  echo "- session_mtime: $SESSION_MTIME"
  echo "- out: $OUT_FILE"
  echo "- status: ok"
} > "$STATUS_FILE"

echo "Checkpointed: $SESSION_FILE -> $OUT_FILE"

#!/usr/bin/env bash
set -euo pipefail

# Summarize many session jsonl files into memory/summaries/.

AGENT_ID="${AGENT_ID:-main}"
OUT_WORKSPACE="${OUT_WORKSPACE:-$(cd "$(dirname "$0")/../.." && pwd)}"
CONFIG_FILE="${OUT_WORKSPACE}/memory_system/config.json"
IN_DIR="${IN_DIR:-}"
LIMIT="${LIMIT:-50}"

if [[ -z "$IN_DIR" ]]; then
  roots=()
  if [[ -n "${MEMORY_SESSION_ROOTS:-}" ]]; then
    while IFS= read -r root; do
      expanded="${root/#\~/$HOME}"
      [[ -n "$expanded" ]] && roots+=("$expanded")
    done < <(printf '%s\n' "${MEMORY_SESSION_ROOTS}" | tr ':' '\n')
  elif [[ -f "$CONFIG_FILE" ]] && command -v python3 >/dev/null 2>&1; then
    while IFS= read -r root; do
      [[ -n "$root" ]] && roots+=("$root")
    done < <(python3 - "$CONFIG_FILE" <<'PY'
import json, pathlib, sys
obj = json.loads(pathlib.Path(sys.argv[1]).expanduser().read_text())
roots = obj.get("sessionRoots") or []
for r in roots:
    p = pathlib.Path(str(r)).expanduser()
    print(str(p))
PY
    )
  else
    roots=(
      "$HOME/.openclaw/agents/$AGENT_ID/sessions"
      "$HOME/.clawdbot/agents/$AGENT_ID/sessions"
      "$HOME/.codex/sessions"
      "$HOME/.codex/agents/$AGENT_ID/sessions"
      "$HOME/.claude/sessions"
      "$HOME/.claude/agents/$AGENT_ID/sessions"
      "$HOME/.claude/projects"
    )
  fi

  for r in "${roots[@]}"; do
    if [[ -d "$r" ]] && ls "$r"/*.jsonl >/dev/null 2>&1; then
      IN_DIR="$r"
      break
    fi
  done
fi

if [[ -z "$IN_DIR" ]]; then
  echo "No session directory found. Set IN_DIR or MEMORY_SESSION_ROOTS." >&2
  exit 2
fi

mkdir -p "$OUT_WORKSPACE/memory_system/data/summaries"

count=0
for f in "$IN_DIR"/*.jsonl; do
  [[ -f "$f" ]] || continue
  base="$(basename "$f" .jsonl)"
  out="$OUT_WORKSPACE/memory_system/data/summaries/${base}.md"
  python3 "$OUT_WORKSPACE/memory_system/tools/summarize_session_jsonl.py" --in "$f" --out "$out" --limit-messages 120 || true
  count=$((count+1))
  if [[ $count -ge $LIMIT ]]; then
    break
  fi
done

echo "Summarized $count session files into $OUT_WORKSPACE/memory_system/data/summaries/"

#!/usr/bin/env bash
set -euo pipefail

WORKDIR="$(cd "$(dirname "$0")/../.." && pwd)"
STATUS_FILE="${WORKDIR}/memory_system/data/LAST_CHECKPOINT.md"

run() {
  cd "$WORKDIR"
  ./memory_system/tools/auto_checkpoint.sh
}

# Capture output; on success keep the normal status file written by auto_checkpoint.sh
OUT=""
if ! OUT=$(run 2>&1); then
  {
    echo "# LAST_CHECKPOINT"
    echo
    echo "- ts: $(date -Iseconds)"
    echo "- status: fail"
    echo "- cwd: $WORKDIR"
    echo "- error: |"
    echo "$OUT" | sed 's/^/  /'
  } > "$STATUS_FILE"

  # Local-only alert (Notification Center). Best-effort.
  /usr/bin/osascript -e 'display notification "auto_checkpoint.sh failed — see memory_system/data/LAST_CHECKPOINT.md" with title "OpenClaw checkpoint"' >/dev/null 2>&1 || true

  echo "$OUT" >&2
  exit 1
fi

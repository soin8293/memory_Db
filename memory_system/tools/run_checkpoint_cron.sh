#!/usr/bin/env bash
set -euo pipefail

# Cron-safe wrapper: run checkpoint silently on success; emit short alert on failure.
WORKDIR="$(cd "$(dirname "$0")/../.." && pwd)"

LOG_DIR="${WORKDIR}/memory_system/data/logs"
mkdir -p "$LOG_DIR"

TS="$(date -Iseconds)"
TMP_OUT="${LOG_DIR}/checkpoint_${TS//:/-}.out"

set +e
(
  cd "$WORKDIR" && ./memory_system/tools/auto_checkpoint.sh
) >"$TMP_OUT" 2>&1
RC=$?
set -e

if [[ $RC -ne 0 ]]; then
  echo "CHECKPOINT_ALERT: auto_checkpoint.sh failed (rc=$RC) at $TS" >&2
  tail -n 60 "$TMP_OUT" >&2
  exit $RC
fi

# Success: stay silent.
exit 0

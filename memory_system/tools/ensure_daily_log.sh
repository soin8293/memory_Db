#!/bin/bash
# Ensure today's daily log exists with a template header.
# Safe to run multiple times (idempotent — won't overwrite existing content).
#
# Usage:
#   bash memory_system/tools/ensure_daily_log.sh
#
# Intended to be called at session start or via cron at midnight.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MEMORY_DIR="$REPO_ROOT/memory_system/daily"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$MEMORY_DIR/$TODAY.md"

mkdir -p "$MEMORY_DIR"

if [ ! -f "$LOG_FILE" ]; then
    cat > "$LOG_FILE" << EOF
# $TODAY

## What happened

## Decisions made

## Blockers / open questions

## Links & references

EOF
    echo "Created daily log: $LOG_FILE"
else
    echo "Daily log exists: $LOG_FILE"
fi

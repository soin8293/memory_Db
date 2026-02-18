#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OPS="$ROOT/memory_system/tools/memory_ops.sh"

echo "Checking memory_ops help output..."
help_out="$(bash "$OPS" help)"
grep -q "session-start" <<<"$help_out"
grep -q "index-fast" <<<"$help_out"
grep -q "index-full" <<<"$help_out"
grep -q "sync" <<<"$help_out"

echo "Checking memory_ops unknown command fails..."
if bash "$OPS" does-not-exist >/dev/null 2>&1; then
  echo "expected unknown command to fail" >&2
  exit 1
fi

echo "Checking memory_ops bootstrap with isolated data dir..."
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/memory_ops_test.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
PROJECT="opsproj_$$"
MEMORY_SYSTEM_DATA_DIR="$TMP_DIR/data" bash "$OPS" bootstrap "$PROJECT" >/dev/null

if [[ ! -d "$TMP_DIR/data/stores/$PROJECT" ]]; then
  echo "expected project store at $TMP_DIR/data/stores/$PROJECT" >&2
  exit 1
fi

echo "OK"

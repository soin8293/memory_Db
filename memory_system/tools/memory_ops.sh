#!/usr/bin/env bash
set -euo pipefail

WORKDIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$WORKDIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$WORKDIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

usage() {
  cat <<'EOF'
memory_ops.sh - consolidated memory pipelines

Usage:
  bash memory_system/tools/memory_ops.sh <command> [args]

Commands:
  help                     Show this help
  bootstrap <project>      Create project store skeleton
  session-start [top]      Ensure daily log + generate session context
  checkpoint               Summarize newest session to memory
  summarize [limit]        Batch summarize sessions (default: 50)
  index-fast               Incremental indexing (WAL + keyword index)
  index-full               Full semantic rebuild (embeddings + FAISS + keywords)
  sync                     checkpoint + index-fast + render nodes
  doctor                   Run health checks
  maintain                 Run maintenance pipeline
EOF
}

run_python() {
  "$PYTHON_BIN" "$@"
}

command="${1:-help}"
shift || true

case "$command" in
  help|-h|--help)
    usage
    ;;

  bootstrap)
    project="${1:-}"
    if [[ -z "$project" ]]; then
      echo "bootstrap requires <project>" >&2
      exit 2
    fi
    run_python -m memory_system.memorydb bootstrap --project "$project"
    ;;

  session-start)
    top="${1:-7}"
    bash "$WORKDIR/memory_system/tools/ensure_daily_log.sh"
    run_python "$WORKDIR/memory_system/tools/session_context.py" --top "$top"
    ;;

  checkpoint)
    bash "$WORKDIR/memory_system/tools/auto_checkpoint.sh"
    ;;

  summarize)
    limit="${1:-50}"
    LIMIT="$limit" OUT_WORKSPACE="$WORKDIR" bash "$WORKDIR/memory_system/tools/summarize_sessions.sh"
    ;;

  index-fast)
    run_python "$WORKDIR/memory_system/tools/delta_index.py" --clear-wal || true
    run_python "$WORKDIR/memory_system/tools/build_keyword_index.py" || true
    ;;

  index-full)
    run_python "$WORKDIR/memory_system/tools/embed_index.py" --embed --backend fastembed --build-faiss --build-keywords
    ;;

  sync)
    bash "$WORKDIR/memory_system/tools/auto_checkpoint.sh"
    run_python "$WORKDIR/memory_system/tools/delta_index.py" --clear-wal || true
    run_python "$WORKDIR/memory_system/tools/build_keyword_index.py" || true
    run_python "$WORKDIR/memory_system/tools/render_nodes.py" || true
    run_python "$WORKDIR/memory_system/tools/render_nodes_for_openclaw.py" || true
    ;;

  doctor)
    bash "$WORKDIR/memory_system/tools/doctor.sh"
    ;;

  maintain)
    WORKSPACE="$WORKDIR" bash "$WORKDIR/memory_system/tools/maintenance.sh"
    ;;

  *)
    echo "Unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac

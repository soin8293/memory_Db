#!/usr/bin/env bash
set -euo pipefail

# Clawdbot Memory Maintenance (hands-off)
# Safe-by-default: generates summaries + proposals; does not auto-apply nodes.

WORKSPACE="${WORKSPACE:-$HOME/clawd}"
WORKSPACE="${WORKSPACE/#\~/$HOME}"

LIMIT_SESSIONS="${LIMIT_SESSIONS:-10}"
AGENT_ID="${AGENT_ID:-main}"

cd "$WORKSPACE"

mkdir -p memory_system/data/maintenance

REPORT_FILE="memory_system/data/maintenance/latest.md"
TS="$(date -Iseconds)"

{
  echo "# Memory Maintenance Report"
  echo
  echo "- ts: $TS"
  echo "- workspace: $WORKSPACE"
  echo

  echo "## Steps"
  echo

  echo "### 1) Render nodes (JSONL -> Markdown)"
  python3 memory_system/tools/render_nodes.py
  echo

  echo "### 1b) Compile policy core (rules -> compact bundle)"
  if [[ -x "memory_system/tools/compile_policy.py" ]]; then
    python3 memory_system/tools/compile_policy.py --workspace "$WORKSPACE" --budget-chars 900
  else
    echo "WARN: compile_policy.py missing; skipping"
  fi
  echo

  echo "### 2) Summarize recent sessions (warm storage)"
  if [[ -x "memory_system/tools/summarize_sessions.sh" ]]; then
    LIMIT="$LIMIT_SESSIONS" OUT_WORKSPACE="$WORKSPACE" AGENT_ID="$AGENT_ID" memory_system/tools/summarize_sessions.sh
  else
    echo "WARN: summarize_sessions.sh missing; skipping"
  fi
  echo

  echo "### 3) Generate promotion proposal from newest summary"
  if [[ -x "memory_system/tools/promote_from_summary.py" ]]; then
    newest="$(ls -t "$WORKSPACE/memory_system/data/summaries"/*.md 2>/dev/null | head -n 1 || true)"
    if [[ -n "$newest" ]]; then
      python3 memory_system/tools/promote_from_summary.py --in "$newest" --workspace "$WORKSPACE" || true
      echo "- newest_summary: $newest"
      echo "- proposals_dir: $WORKSPACE/memory_system/data/proposals"
    else
      echo "WARN: No summaries found; skipping proposal."
    fi
  else
    echo "WARN: promote_from_summary.py missing; skipping"
  fi
  echo

  echo "### 3b) Prune expired excerpts (derived artifacts)"
  if [[ -x "memory_system/tools/prune_excerpts.py" ]]; then
    python3 memory_system/tools/prune_excerpts.py || true
  else
    echo "WARN: prune_excerpts.py missing; skipping"
  fi
  echo

  echo "### 4) Reindex memory"
  clawdbot memory index --agent main || true
  echo

  echo "### 5) Smoke checks"
  if [[ -x "memory_system/tools/smoke_memory.sh" ]]; then
    memory_system/tools/smoke_memory.sh || true
  else
    echo "WARN: smoke_memory.sh missing"
  fi

  echo "\n## Done" 
} | tee "$REPORT_FILE"


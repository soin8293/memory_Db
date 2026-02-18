# Pipelines and Single Commands

This repository consolidates operational memory pipelines behind one command:

```bash
bash memory_system/tools/memory_ops.sh <command>
```

## Canonical commands

| Command | What it runs | Typical use |
|---|---|---|
| `bootstrap <project>` | MemoryDB store bootstrap | Start a new project memory scope |
| `session-start [top]` | `ensure_daily_log.sh` + `session_context.py` | Beginning of a chat/build session |
| `checkpoint` | `auto_checkpoint.sh` | Pull newest session JSONL into summaries |
| `summarize [limit]` | `summarize_sessions.sh` | Backfill many session logs |
| `index-fast` | `delta_index.py --clear-wal` + `build_keyword_index.py` | Frequent incremental indexing |
| `index-full` | `embed_index.py --embed --build-faiss --build-keywords` | Full semantic rebuild |
| `sync` | checkpoint + index-fast + node renders | Most common daily command |
| `doctor` | `doctor.sh` | Health + config validation |
| `maintain` | `maintenance.sh` | Periodic maintenance workflow |

## Agent-oriented defaults

Use these three commands as the primary agent workflow:

```bash
# 1) At session start
bash memory_system/tools/memory_ops.sh session-start

# 2) During/after work
bash memory_system/tools/memory_ops.sh sync

# 3) If search quality drifts or after bulk imports
bash memory_system/tools/memory_ops.sh index-full
```

## Session source roots

Session log roots are read from:
- `memory_system/config.json` (`sessionRoots`)
- optional runtime override: `MEMORY_SESSION_ROOTS` (colon-separated)

Example:

```bash
export MEMORY_SESSION_ROOTS="$HOME/.codex/sessions:$HOME/.claude/projects:$HOME/.openclaw/agents/main/sessions"
```

## Notes

- All commands are idempotent-oriented and safe for repeated runs.
- `index-full` requires semantic dependencies (`pip install -e '.[semantic]'`).

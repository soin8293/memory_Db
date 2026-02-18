# memory_Db

AmirahCo's local-first MemoryDB add-on for AI agents.

`memory_Db` provides durable agent memory with:
- append-only JSONL ledger (`nodes.jsonl`)
- hybrid recall (OpenClaw search -> FAISS -> keyword index -> FTS/scan fallback)
- project-scoped memory stores for complex app builds
- tooling for Codex, Claude, OpenClaw, and custom agents

In practice, users create a project `MemoryDB` object and treat it as the
agent's memory database: durable facts + embedding-backed retrieval for ongoing
context while building software.

## Maintainer

Built and maintained by **AmirahCo**.

## Install

From repository root:

```bash
python3 -m pip install -e .
```

Optional semantic stack (FAISS + FastEmbed):

```bash
python3 -m pip install -e '.[semantic]'
```

## Quickstart

```bash
# Bootstrap project memory store
bash memory_system/tools/memory_ops.sh bootstrap my-project

# Add/retrieve memory via MemoryDB object API
python3 -m memory_system.memorydb jot --project my-project "token refresh is 15 minutes"
python3 -m memory_system.memorydb lookup --project my-project "token refresh"

# Consolidated pipelines
bash memory_system/tools/memory_ops.sh session-start
bash memory_system/tools/memory_ops.sh sync
```

## Consolidated pipeline commands

Use one wrapper for common workflows:

```bash
bash memory_system/tools/memory_ops.sh help
```

Most used:
- `session-start`: daily log + session context injection
- `checkpoint`: summarize latest session
- `index-fast`: WAL + keyword incremental indexing
- `index-full`: full embeddings + FAISS + keyword rebuild
- `sync`: checkpoint + index-fast + render views
- `doctor`: health/consistency checks

## Runtime paths

Default runtime data resolution order:
1. `MEMORY_SYSTEM_DATA_DIR`
2. `MEMORY_SYSTEM_HOME` (uses `<home>/data`)
3. package-local `memory_system/data` (source checkout)
4. `~/.openclaw/memorydb/data` fallback

Example:

```bash
export MEMORY_SYSTEM_HOME="$HOME/.openclaw/memorydb"
```

## Session roots (OpenClaw, Codex, Claude)

`memory_Db` can ingest session `.jsonl` logs from multiple agent runtimes.

Default `memory_system/config.json` roots include:
- `~/.openclaw/agents/main/sessions`
- `~/.clawdbot/agents/main/sessions`
- `~/.codex/sessions`
- `~/.codex/agents/main/sessions`
- `~/.claude/sessions`
- `~/.claude/agents/main/sessions`
- `~/.claude/projects`

You can override with:

```bash
export MEMORY_SESSION_ROOTS="$HOME/.codex/sessions:$HOME/.claude/projects:$HOME/.openclaw/agents/main/sessions"
```

## Repository docs

- Core guide: `memory_system/README.md`
- Agent onboarding: `memory_system/docs/AGENT_MEMORY_ONBOARDING.md`
- Integration: `memory_system/docs/INTEGRATION.md`
- Docs status map: `memory_system/docs/STATUS.md`
- Contributing: `CONTRIBUTING.md`
- Security: `SECURITY.md`
- Code of conduct: `CODE_OF_CONDUCT.md`
- Release checklist: `RELEASE_CHECKLIST.md`

## License

MIT (`LICENSE`).

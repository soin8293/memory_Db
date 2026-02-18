# OpenClaw Memory System

Persistent, structured memory for AI agents across sessions. Local-first, file-based, no cloud dependency. Works with any agent framework (Claude Code, OpenClaw, Codex, custom agents).

Maintained by **AmirahCo**.

**Why this exists:** LLM agents lose context between sessions. This system gives agents a durable memory layer — write facts, search them later, inject relevant context at session start. Everything is append-only files on disk.

---

## Portable install (GitHub release)

```bash
python3 -m pip install -e .
```

By default, runtime data is resolved in this order:
- `MEMORY_SYSTEM_DATA_DIR` (explicit data directory)
- `MEMORY_SYSTEM_HOME` (uses `<home>/data`)
- package-local `memory_system/data` (source checkout)
- `~/.openclaw/memorydb/data` (fallback for non-checkout installs)

Example:

```bash
export MEMORY_SYSTEM_HOME="$HOME/.openclaw/memorydb"
```

Session roots for checkpoint/summarization are configured in `config.json`.
Default roots include OpenClaw, Clawdbot, Codex, and Claude locations.
You can override at runtime with a colon-separated env var:

```bash
export MEMORY_SESSION_ROOTS="$HOME/.codex/sessions:$HOME/.claude/projects:$HOME/.openclaw/agents/main/sessions"
```

---

## Quick start (for agents)

**Read first:** [`docs/AGENT_MEMORY_ONBOARDING.md`](docs/AGENT_MEMORY_ONBOARDING.md) — the full onboarding guide.

```bash
# Set your Python (adjust to your env)
PYTHON=python3

# 1. Write a memory node
$PYTHON memory_system/tools/add_node.py \
  --type decision --id decision:use-postgres \
  --scope my-project --text "We chose Postgres over SQLite for production" \
  --tags decision database

# 2. Search memory (semantic + keyword hybrid)
$PYTHON memory_system/tools/recall.py --query "database choice" --global

# 3. Query by structure (type, scope, tag)
$PYTHON memory_system/tools/query_nodes.py --scope my-project --type decision

# 4. Inject context at session start
$PYTHON memory_system/tools/session_context.py --top 7
```

### Per-project quick notes (jot API)

For low-friction note capture during work — no schema, no tags required:

```bash
# Quick jot
$PYTHON -m memory_system.memorydb jot --project my-project "user prefers dark mode"

# Batch jot (multiple notes at once)
$PYTHON -m memory_system.memorydb jot-batch --project my-project \
  "API uses JWT auth" "rate limit is 100/min" "deploy via GitHub Actions"

# Search jots
$PYTHON -m memory_system.memorydb lookup --project my-project "auth"

# View recent working set
$PYTHON -m memory_system.memorydb ws --project my-project -n 10
```

### Project-local stores

Projects can have their own memory store directory instead of using the central one:

```bash
# Bootstrap a project-local store
$PYTHON -m memory_system.memorydb bootstrap --project my-project --store-path /path/to/my-project/memory_db

# All commands accept --store-path
$PYTHON -m memory_system.memorydb jot --project my-project --store-path ./memory_db "local note"
$PYTHON -m memory_system.memorydb ws --project my-project --store-path ./memory_db -n 5
```

### One-command pipelines

Use the consolidated wrapper for day-to-day operations:

```bash
bash memory_system/tools/memory_ops.sh help
```

Most common:

```bash
# Session start: ensure daily log + generate context block
bash memory_system/tools/memory_ops.sh session-start

# Sync latest session into memory + incremental indexing + render
bash memory_system/tools/memory_ops.sh sync

# Full semantic rebuild (embeddings + FAISS + keywords)
bash memory_system/tools/memory_ops.sh index-full
```

---

## Directory structure

```
memory_system/
├── README.md                  # This file
├── memorydb.py                # Core MemoryDB class (Python API)
├── __init__.py                # Package init
├── config.json                # Session roots, checkpoint config
├── requirements.txt           # Dependencies (faiss-cpu, numpy, fastembed)
├── .gitignore                 # Ignores data/, daily/, nodes_rendered/, projects/
│
├── tools/                     # All executable tools (35 Python + 14 shell)
│   ├── add_node.py            #   Write nodes
│   ├── recall.py              #   Semantic search
│   ├── query_nodes.py         #   Structured query
│   ├── intent_gate.py         #   Intent classification
│   ├── session_context.py     #   Session startup injection
│   ├── ... (see Tools Reference below)
│   └── doctor.sh              #   Health check
│
├── embeddings/                # Local-only embedding backends
│   ├── factory.py             #   Backend factory (hash, fastembed)
│   ├── fastembed_embedder.py  #   FastEmbed local model
│   ├── hash_embedder.py       #   Deterministic hash (testing)
│   ├── daemon.py              #   Persistent inference daemon
│   ├── quantize.py            #   int8 quantization (4x storage reduction)
│   └── embedder.py            #   Protocol interface
│
├── docs/                      # Architecture and specification docs
│   ├── AGENT_MEMORY_ONBOARDING.md  # START HERE — full agent guide
│   ├── NODES_SPEC.md               # Node schema and rules
│   ├── EMBEDDINGS_SPEC.md          # Vector index specification
│   ├── INTEGRATION.md              # How to integrate into your agent
│   ├── PIPELINES.md                # Cron jobs, triggers, automation
│   ├── memory_guide.md             # Architecture deep-dive
│   ├── architecture.md             # Design overview
│   ├── architecture_diagram.txt    # ASCII diagram
│   └── custom_vector_architecture.md  # Custom vector store design
│
├── templates/                 # Scaffolding for new projects
│   ├── project_dossier.md     #   Project metadata template
│   └── example_nodes.jsonl    #   Example nodes for reference
│
├── policy/                    # Compiled policy rules
│   ├── core.md                #   Always-on rules (generated from nodes)
│   └── core.stats.json        #   Compilation stats
│
├── tests/                     # Test suite
│   └── test_scope_leak.sh     #   Scope isolation regression test
│
├── data/                      # Private data (GITIGNORED)
│   ├── nodes.jsonl            #   SOURCE OF TRUTH — append-only ledger
│   ├── wal.jsonl              #   Write-ahead log for incremental indexing
│   ├── index.json             #   Master routing index by scope
│   ├── keyword_index.json     #   Inverted keyword index (O(1) lookup)
│   ├── embeddings.sqlite      #   Embedding chunks (SQLite)
│   ├── embeddings.faiss       #   FAISS vector index
│   ├── embeddings.ids.json    #   FAISS ID → node ID mapping
│   ├── topics.json            #   Topic config for session chunking
│   ├── state.json             #   Operational state
│   ├── events.jsonl           #   Event log
│   ├── NODES.md               #   Rendered markdown of all nodes
│   ├── WORKING_SET.md         #   Current injected context
│   ├── LAST_CHECKPOINT.md     #   Last checkpoint status
│   ├── stores/                #   Per-project MemoryDB stores
│   ├── models/fastembed/      #   Cached embedding models (~63MB)
│   ├── summaries/             #   Session summaries
│   ├── excerpts/              #   Session excerpts
│   ├── chat-history/          #   Chat history exports
│   ├── proposals/             #   Memory promotion proposals
│   ├── logs/                  #   Tool execution logs
│   ├── maintenance/           #   Maintenance reports
│   ├── locks/                 #   Concurrency control
│   └── ops/                   #   Operational logs (gateway restarts, etc.)
│
├── daily/                     # Daily logs (GITIGNORED)
│   └── YYYY-MM-DD.md          #   Ephemeral daily context
│
├── projects/                  # Project dossiers (GITIGNORED)
│   └── <slug>.md              #   Per-project state and metadata
│
└── nodes_rendered/            # Individual node markdown files (GITIGNORED)
    └── <node-id>.md           #   One file per node for indexing
```

**What's publishable vs private:**
- Everything except `data/`, `daily/`, `projects/`, and `nodes_rendered/` is safe to publish
- The `.gitignore` handles this automatically

---

## Architecture

### Core concept: nodes

Everything in the memory system is a **node** — a single fact stored in `data/nodes.jsonl`:

```json
{
  "id": "decision:use-postgres",
  "type": "decision",
  "scope": "my-project",
  "ts": "2026-02-14T10:30:00-07:00",
  "text": "We chose Postgres over SQLite for production due to concurrent write needs",
  "tags": ["decision", "database", "infrastructure"],
  "links": ["incident:sqlite-lock-contention"],
  "meta": {}
}
```

**Node types:** `project`, `rule`, `decision`, `incident`, `note`, `pointer`

**Scopes:** `global` (cross-project) or a project slug (e.g., `my-project`)

Full schema: [`docs/NODES_SPEC.md`](docs/NODES_SPEC.md)

### How retrieval works

The system cascades through multiple backends to find relevant memories:

```
recall.py --query "database choice"
    │
    ├─→ 1. FAISS vector search (semantic similarity, fastest)
    ├─→ 2. Keyword index (inverted word index, O(1) per term)
    ├─→ 3. SQLite FTS (full-text search on chunks table)
    └─→ 4. Linear scan (substring match, fallback)

Results are merged, deduplicated, and ranked by relevance + recency.
```

### Data flow

```
Write path:
  Agent → add_node.py → nodes.jsonl (append) → WAL → delta_index.py → embeddings

Read path:
  Agent → recall.py → FAISS/keyword/FTS → ranked results
  Agent → query_nodes.py → structured filter → exact matches
  Agent → session_context.py → top-N rules/decisions → context block

Maintenance path:
  Cron → auto_checkpoint.sh → summarize session → promote candidates → nodes
```

### MemoryDB class (Python API)

`memorydb.py` provides a high-level Python interface:

Think of `MemoryDB` as a project-level memory database object for agents:
- durable node storage
- embedding-capable semantic recall (when indexed)
- keyword/FTS fallbacks
- scoped context continuity across sessions

```python
from memory_system.memorydb import MemoryDB

# Global store
db = MemoryDB()

# Project-scoped store (central)
db = MemoryDB(project="my-project")

# Project-local store (in your project directory)
db = MemoryDB(project="my-project", store_path="./memory_db")

# Operations
db.jot("user prefers dark mode")                          # Quick note
db.jot_batch(["fact 1", "fact 2", "fact 3"])              # Batch notes
results = db.lookup("dark mode")                           # Keyword search
recent = db.working_set(n=10)                              # Recent context
db.add_node(id="decision:theme", type_="decision",         # Structured node
            text="Dark mode is default", tags=["ui"])
db.recall("theme preferences")                             # Semantic search
db.query(type_="decision")                                 # Structured query
```

CLI interface:

```bash
$PYTHON -m memory_system.memorydb <command> [options]

Commands: add, recall, query, bootstrap, tags, jot, jot-batch, lookup, ws
```

---

## Tools reference

### Writing memory

| Tool | What it does | When to use |
|------|-------------|-------------|
| `tools/add_node.py` | Append a structured node to `nodes.jsonl` | Recording decisions, rules, incidents with full metadata |
| `memorydb.py jot` | Quick unstructured note | Capturing context mid-task without stopping to think about schema |
| `memorydb.py jot-batch` | Multiple notes at once | End-of-task brain dump |
| `memorydb.py add` | Add node via MemoryDB CLI | Same as add_node.py but through the unified CLI |

### Reading memory

| Tool | What it does | When to use |
|------|-------------|-------------|
| `tools/recall.py` | Semantic + keyword hybrid search | "What do we know about X?" — fuzzy, natural language |
| `tools/query_nodes.py` | Filter by scope/type/tag/text | "Show all decisions for project Y" — structured, exact |
| `tools/faiss_search.py` | Direct FAISS vector search | Low-level vector similarity (usually use recall.py instead) |
| `tools/embed_query.py` | Query SQLite embeddings | Low-level chunk search (usually use recall.py instead) |
| `tools/hierarchical_recall.py` | Multi-stage coarse→fine retrieval | Large memory stores where single-pass recall is too noisy |
| `memorydb.py lookup` | Keyword search within a project store | Quick project-scoped search |
| `memorydb.py ws` | Recent working set | "What have I been noting?" — context refresh |
| `memorydb.py recall` | Semantic search via MemoryDB | Same as recall.py but scoped to a project |
| `memorydb.py query` | Structured query via MemoryDB | Same as query_nodes.py but scoped to a project |

### Session and context management

| Tool | What it does | When to use |
|------|-------------|-------------|
| `tools/session_context.py` | Generate top-N rules/decisions for injection | Session startup — gives agents their "working memory" |
| `tools/intent_gate.py` | Classify user intent (memory/security/ops/project) | Route messages to the right handler without embeddings |
| `tools/select_rules.py` | Select extra rules based on intent | Augment session context with situation-specific rules |
| `tools/compile_policy.py` | Compile always-on policy from nodes | Generate `policy/core.md` from rule-type nodes |
| `tools/update_working_set.py` | Update `WORKING_SET.md` | Refresh the injected context bundle |

### Indexing and maintenance

| Tool | What it does | When to use |
|------|-------------|-------------|
| `tools/embed_index.py` | Build embeddings + FAISS + keyword indexes | Full rebuild after bulk changes |
| `tools/delta_index.py` | Incremental index update from WAL | After adding a few nodes (faster than full rebuild) |
| `tools/build_keyword_index.py` | Build inverted keyword index | Rebuild keyword search after edits |
| `tools/rebuild_index.py` | Regenerate `data/index.json` from nodes | Fix routing index after manual edits |
| `tools/render_nodes.py` | Render nodes.jsonl → NODES.md | Make nodes searchable by markdown-only indexers |
| `tools/render_nodes_for_openclaw.py` | Render nodes → individual .md files | One file per node for OpenClaw memory_search |

### Session processing

| Tool | What it does | When to use |
|------|-------------|-------------|
| `tools/summarize_session_jsonl.py` | Summarize a session .jsonl → markdown | Extract key events from raw session logs |
| `tools/excerpt_session.py` | Create focused excerpt from session | Pull specific topic excerpts with TTL |
| `tools/chunk_session_topics.py` | Chunk session into topic buckets | Break long sessions into searchable topics |
| `tools/promote_from_summary.py` | Propose durable nodes from summaries | Identify decisions/rules/incidents worth keeping |
| `tools/prune_excerpts.py` | Clean up expired excerpts | Garbage collection for derived artifacts |

### Automation and health

| Tool | What it does | When to use |
|------|-------------|-------------|
| `tools/memory_ops.sh` | Unified command wrapper for key pipelines | Default entrypoint for agents and humans |
| `tools/auto_checkpoint.sh` | Summarize latest session automatically | Runs on cron (every 10 min via launchd) |
| `tools/auto_checkpoint_wrapper.sh` | Wrapper with error capture | Called by the plist daemon |
| `tools/run_checkpoint_cron.sh` | Cron-safe checkpoint runner | Silent on success, alerts on failure |
| `tools/maintenance.sh` | Full maintenance pipeline | Generate summaries + proposals (hands-off) |
| `tools/doctor.sh` | Diagnostic health check | Validate index consistency, permissions, layouts |
| `tools/ensure_daily_log.sh` | Create today's daily log | Idempotent — safe to call multiple times |
| `tools/security_check.sh` | Detect exposure footguns | Check for secrets, permissions issues |
| `tools/summarize_sessions.sh` | Batch summarize many sessions | Process backlog of session logs |

### Other tools

| Tool | What it does |
|------|-------------|
| `tools/stopwords_basic.txt` | 126 English stopwords for keyword filtering |

---

## Embedding backends

The system supports two local embedding backends (no API calls):

| Backend | Use case | Quality | Speed |
|---------|----------|---------|-------|
| `hash` | Testing, CI, pipeline validation | Non-semantic (fingerprint only) | Instant |
| `fastembed` | Production semantic search | Good (all-MiniLM-L6-v2) | ~50ms/query |

The `fastembed` backend downloads a ~63MB model on first use to `data/models/fastembed/`. After that, everything is local.

An optional **embedding daemon** (`embeddings/daemon.py`) keeps the model loaded in memory for fast inference via Unix socket.

See [`docs/EMBEDDINGS_SPEC.md`](docs/EMBEDDINGS_SPEC.md) for the full specification.

---

## Documentation index

| Document | What it covers |
|----------|---------------|
| [`docs/AGENT_MEMORY_ONBOARDING.md`](docs/AGENT_MEMORY_ONBOARDING.md) | **Start here.** Full guide for agents: setup, usage patterns, examples |
| [`docs/NODES_SPEC.md`](docs/NODES_SPEC.md) | Node schema, required fields, type definitions, editing rules |
| [`docs/EMBEDDINGS_SPEC.md`](docs/EMBEDDINGS_SPEC.md) | Vector index schema, chunking strategy, backend specs |
| [`docs/INTEGRATION.md`](docs/INTEGRATION.md) | How to wire the memory system into your agent |
| [`docs/PIPELINES.md`](docs/PIPELINES.md) | Cron jobs, triggers, checkpoint automation |
| [`docs/memory_guide.md`](docs/memory_guide.md) | Architecture deep-dive, data flow, storage layout |
| [`docs/architecture.md`](docs/architecture.md) | Design overview and principles |
| [`docs/architecture_diagram.txt`](docs/architecture_diagram.txt) | ASCII architecture diagram |
| [`docs/custom_vector_architecture.md`](docs/custom_vector_architecture.md) | Custom vector store design spec |
| [`templates/project_dossier.md`](templates/project_dossier.md) | Template for project metadata dossiers |
| [`templates/example_nodes.jsonl`](templates/example_nodes.jsonl) | Example nodes showing all types |
| [`policy/core.md`](policy/core.md) | Compiled always-on policy rules |

---

## Integration patterns

### Pattern 1: Session startup injection

At the start of every agent session, inject relevant context:

```bash
# Get top 7 rules/decisions as a context block
$PYTHON memory_system/tools/session_context.py --top 7
```

This returns a markdown block you can prepend to your system prompt or inject as a user message.

### Pattern 2: Intent-driven recall

When processing user messages, classify intent first to avoid unnecessary embedding calls:

```bash
# Classify: returns "memory", "security", "ops", or "project"
$PYTHON memory_system/tools/intent_gate.py "remember we decided to use Postgres"

# Then recall only if intent is memory-related
$PYTHON memory_system/tools/recall.py --query "Postgres decision" --global
```

### Pattern 3: Project-local memory

Each project can have its own isolated memory store:

```bash
# Bootstrap (one-time)
$PYTHON -m memory_system.memorydb bootstrap --project my-app --store-path /path/to/my-app/memory_db

# Use throughout the project
$PYTHON -m memory_system.memorydb jot --project my-app --store-path ./memory_db "the thing to remember"
$PYTHON -m memory_system.memorydb lookup --project my-app --store-path ./memory_db "keyword"
```

### Pattern 4: End-of-session promotion

After a work session, promote durable facts to long-term memory:

```bash
# 1. Summarize the session log
$PYTHON memory_system/tools/summarize_session_jsonl.py \
  --in ~/.openclaw/agents/main/sessions/latest.jsonl \
  --out memory_system/data/summaries/session-name.md

# 2. Extract promotion candidates (local heuristics, no LLM)
$PYTHON memory_system/tools/promote_from_summary.py \
  --in memory_system/data/summaries/session-name.md

# 3. Review and apply (interactive)
$PYTHON memory_system/tools/promote_from_summary.py \
  --in memory_system/data/summaries/session-name.md --apply
```

### Pattern 5: Daily logging

Keep a running log of daily context:

```bash
# Create today's log (idempotent)
bash memory_system/tools/ensure_daily_log.sh

# Log lives at memory_system/daily/YYYY-MM-DD.md
# Agents can append notes throughout the day
```

---

## Health checks

```bash
# Full diagnostic (index consistency, permissions, stale data)
bash memory_system/tools/doctor.sh

# Public command wrapper (doctor + index + session pipelines)
bash memory_system/tools/memory_ops.sh doctor

# Security check (secrets exposure, permissions)
bash memory_system/tools/security_check.sh
```

---

## Dependencies

```
faiss-cpu    # Vector similarity search
numpy        # Array operations for embeddings
fastembed    # Local embedding model (optional — hash backend works without it)
```

Install: `pip install -r requirements.txt`

The system degrades gracefully — if fastembed isn't installed, it falls back to the hash backend (non-semantic but functional for testing and keyword search).

---

## Design principles

1. **File-based, append-only** — `nodes.jsonl` is the source of truth. Everything else is derived.
2. **Local-first** — No cloud APIs, no network calls. Runs on your machine.
3. **Agent-agnostic** — Works with Claude Code, OpenClaw, Codex, or any agent that can run Python/bash.
4. **Graceful degradation** — Missing indexes? Falls back to linear scan. No fastembed? Uses hash backend.
5. **Deterministic where possible** — Same input, same output. No LLM in the critical path.
6. **Scope isolation** — Project memories don't leak across projects.
7. **Publishable core** — Code is open-source ready. Private data is gitignored.

# Agent Memory Onboarding

**Read this file first. If you only read one file, read this one.**

---

## Quickstart (30-second version)

```bash
# Project bootstrap + session startup
bash memory_system/tools/memory_ops.sh bootstrap my-project
bash memory_system/tools/memory_ops.sh session-start

# Track details while building
python3 -m memory_system.memorydb jot --project my-project "We decided X because Y."

# Sync latest session + index updates
bash memory_system/tools/memory_ops.sh sync
```

Run commands from the repository root (or with installed package entrypoints). Nodes append to `memory_system/data/nodes.jsonl`. Never edit old lines.

Session ingestion roots are read from `memory_system/config.json` and can be
overridden via `MEMORY_SESSION_ROOTS` (colon-separated paths), e.g.:

```bash
export MEMORY_SESSION_ROOTS="$HOME/.codex/sessions:$HOME/.claude/projects:$HOME/.openclaw/agents/main/sessions"
```

Consolidated pipelines are exposed through:

```bash
bash memory_system/tools/memory_ops.sh help
```

---

## 1. Mental model

Two layers, both required:

| Layer | What | Where | When to use |
|-------|------|-------|-------------|
| **File memory** (source of truth) | Append-only node ledger + daily logs + curated MEMORY.md | `memory_system/data/nodes.jsonl`, `memory_system/daily/YYYY-MM-DD.md`, `MEMORY.md` | Always |
| **Vector memory** (search) | Embeddings built from nodes for semantic retrieval | `memory_system/data/embeddings.sqlite` | Automatic (derived from nodes) |

**Rule: nodes are the canonical facts.** Everything else (embeddings, rendered markdown, indexes) is derived and rebuildable.

For agents, the `MemoryDB` object is the operational interface to this system:
it behaves as the project's memory database, combining durable memory writes and
embedding-backed retrieval to preserve context across chat sessions.

---

## 2. Where everything lives

```
<repo-root>/
├── MEMORY.md                          # curated long-term memory (short!)
├── memory_system/
│   ├── memorydb.py                    # MemoryDB Python class
│   ├── tools/                         # all executable tools (see §5)
│   ├── embeddings/                    # embedding utilities
│   ├── docs/                          # specs & guides (this file lives here)
│   │   ├── NODES_SPEC.md
│   │   ├── EMBEDDINGS_SPEC.md
│   │   ├── PIPELINES.md
│   │   └── memory_guide.md
│   ├── templates/                     # templates
│   ├── data/                          # all generated/private data
│   │   ├── nodes.jsonl                # THE source of truth (append-only)
│   │   ├── embeddings.sqlite          # vector index (derived, deletable)
│   │   ├── wal.jsonl                  # write-ahead log for incremental index
│   │   ├── index.json                 # routing table
│   │   ├── topics.json                # topic registry
│   │   ├── LAST_CHECKPOINT.md         # checkpoint proof
│   │   └── summaries/                 # session summaries
│   ├── daily/                         # daily logs
│   │   └── YYYY-MM-DD.md             # daily log (journal, not wiki)
│   ├── projects/                      # per-project dossiers
│   │   └── <slug>.md
│   ├── nodes_rendered/                # auto-generated markdown per node
│   └── .gitignore
```

---

## 3. Node schema

Every node in `nodes.jsonl` is one JSON line:

```json
{
  "id": "decision:my-project-auth-flow",
  "type": "decision",
  "ts": "2026-02-10T14:30:00-07:00",
  "scope": "my-project",
  "text": "Use OAuth2 PKCE flow, not implicit grant.",
  "tags": ["decision", "my-project", "security"],
  "links": [],
  "meta": {}
}
```

**Required fields:** `id`, `type`, `ts`
**Recommended:** `scope`, `text`, `tags`

### ID scheme

| Prefix | Use |
|--------|-----|
| `proj:<slug>` | Project registration |
| `decision:<slug>` | Decision made |
| `rule:<slug>` | Constraint or rule |
| `incident:<slug>` | Failure or incident |
| `note:<slug>` | General fact (default if unsure) |
| `ptr:<slug>` | Pointer to external resource |
| `excerpt:<slug>` | Session excerpt |

Slugs: lowercase + hyphens only.

### Type values
`project` | `rule` | `decision` | `incident` | `note` | `pointer` | `excerpt`

### Tags

**Required base tags** (use at least one):
`decision` · `constraint` · `source` · `insight` · `risk` · `next-step` · `contact`

**Optional:** `metric` · `deadline` · `process` · `tool` · `assumption`

Keep tags short and reusable. No one-off tags.

---

## 4. When to write memory

**Write a node when:**
- A decision is made
- A rule or constraint is established
- A preference is expressed
- Project context or dependency is discovered
- A source/citation needs to be retained
- An incident or operational failure occurs
- User says "remember this"

**Don't write:**
- Ephemeral chat or filler
- Speculation without a decision
- Secrets (unless user explicitly asks)

**Ask-first default:** If the user is explicit (text + scope), write immediately. If ambiguous, ask a 1-line confirmation.

---

## 5. Tools reference

All tools live in `memory_system/tools/`. Run from repository root:

### Writing

**Add a node** (primary — use this for all memory writes):
```bash
python3 memory_system/tools/add_node.py \
  --type decision \
  --id decision:my-project-auth-flow \
  --scope my-project \
  --text "Use OAuth2 PKCE flow, not implicit grant." \
  --tags decision my-project security
```
This auto-renders markdown views and triggers indexing. You don't need to manually update embeddings.

**Quick jot** (low-friction — auto-generates ID, skips tag validation):
```bash
# Single jot
python3 -m memory_system.memorydb jot --project my-project "the auth endpoint returns 403 not 401 on expired tokens"

# Batch jot (multiple details at once)
python3 -m memory_system.memorydb jot-batch --project my-project "detail one" "detail two" "detail three"
```
Use jot for tracking many small observations mid-session. No need to craft IDs or tags — it's designed for agents juggling 200+ details. Any agent can bootstrap a project store and start jotting immediately.

**Add via MemoryDB** (formal nodes with tag validation — for decisions/rules):
```bash
python3 -m memory_system.memorydb add \
  --project my-project \
  --id decision:my-project-auth-flow \
  --type decision \
  --text "Use OAuth2 PKCE flow, not implicit grant." \
  --tags decision my-project
```

**Python API** (from scripts/agents):
```python
from memory_system.memorydb import MemoryDB

# Central store (default — stores in <repo-root>/memory_db/<project>/)
db = MemoryDB(project="my-project")

# Project-local store (stores in a directory you choose)
db = MemoryDB(project="my-project", store_path="/path/to/my-project/memory_db")

# Low-friction jot path
db.jot("the auth endpoint returns 403 not 401 on expired tokens")
db.jot_batch(["pagination uses cursors", "rate limit is 100/min", "upload max 10MB"])
db.lookup("rate limit")       # → matching text strings
db.working_set(n=10)          # → last 10 jots

# Formal node path
db.add_node(
    node_id="decision:my-project-auth-flow",
    node_type="decision",
    text="Use OAuth2 PKCE flow, not implicit grant.",
    tags=["decision", "my-project"],
)
```

### Reading

**Semantic recall** (primary search — hybrid FTS + vector + heuristic fallback):
```bash
python3 memory_system/tools/recall.py "auth flow decision"
python3 memory_system/tools/recall.py --global "rate limit reset"
```

**Query by scope/type** (structured lookup):
```bash
python3 memory_system/tools/query_nodes.py --scope my-project --type decision
python3 memory_system/tools/query_nodes.py --scope global --type rule
```

**Quick lookup** (fast keyword search scoped to a project — for finding jots):
```bash
python3 -m memory_system.memorydb lookup --project my-project "rate limit"
```

**Working set** (recent jots for this project — what am I tracking?):
```bash
python3 -m memory_system.memorydb ws --project my-project -n 10
```

**FAISS vector search** (direct vector similarity):
```bash
python3 memory_system/tools/faiss_search.py "browser automation strategy"
```

### Intent detection

**Classify user intent before acting** (detects memory/security/ops keywords):
```bash
python3 memory_system/tools/intent_gate.py "remember we decided to use Lever only"
```
Returns JSON with `intents` (e.g. `memory.recall`, `security.external_action`) and `buckets`.
If `memory.recall` is detected → auto-run `recall.py` with the topic keywords.

### Session startup

**Auto-inject active constraints** (run at session start per AGENTS.md step 6):
```bash
bash memory_system/tools/memory_ops.sh session-start
```

**If you need project-scoped context only**:
```bash
python3 memory_system/tools/session_context.py --scope my-project --top 5
```

### Indexing & maintenance

**Fast daily sync** (checkpoint + incremental index + renders):
```bash
bash memory_system/tools/memory_ops.sh sync
```

**Build/rebuild all indexes** (embeddings + FAISS + keyword index):
```bash
bash memory_system/tools/memory_ops.sh index-full
```

**Build keyword index only** (fast, no model needed):
```bash
python3 memory_system/tools/build_keyword_index.py
```

**Process incremental updates (WAL):**
```bash
bash memory_system/tools/memory_ops.sh index-fast
```

**System health check:**
```bash
bash memory_system/tools/memory_ops.sh doctor
```

**Rebuild routing index** (memory_system/data/index.json from nodes.jsonl):
```bash
python3 memory_system/tools/rebuild_index.py
```

**Chunk a session transcript into nodes:**
```bash
python3 memory_system/tools/chunk_session_topics.py \
  --in ~/.clawdbot/agents/main/sessions/<id>.jsonl \
  --scope my-project \
  --write-nodes --update-index \
  --report-path memory_system/data/summaries/chunk_report.md \
  --auto-buckets
```

**Health check:**
```bash
bash memory_system/tools/memory_ops.sh doctor
```

### Per-project MemoryDB

**Central store** (default — stores in `<repo-root>/memory_db/<project>/`):
```bash
python3 -m memory_system.memorydb bootstrap --project my-project
```

**Project-local store** (stores inside the project directory — use `--store-path`):
```bash
python3 -m memory_system.memorydb bootstrap --project my-project --store-path /path/to/my-project/memory_db
```

**Add/query/recall through MemoryDB:**
```bash
# Central store (omit --store-path)
python3 -m memory_system.memorydb add --project my-project --id decision:my-project-auth-flow --type decision --text "..." --tags decision my-project
python3 -m memory_system.memorydb query --project my-project --type decision

# Project-local store (include --store-path)
python3 -m memory_system.memorydb jot --project my-project --store-path /path/to/my-project/memory_db "detail"
python3 -m memory_system.memorydb lookup --project my-project --store-path /path/to/my-project/memory_db "keyword"
```

See `memory_system/docs/memory_guide.md` for full MemoryDB documentation.

---

## 6. The write workflow (step by step)

Every time you store information, follow this order:

1. **Chunk** into small facts (1 fact per node, 1-3 sentences)
2. **Append nodes** via `add_node.py` (handles rendering + indexing automatically)
3. **Update project dossier** (`memory_system/projects/<slug>.md`) if project-specific
4. **Update routing index** (`memory_system/data/index.json`) with new node IDs
5. **Log daily** (`memory_system/daily/YYYY-MM-DD.md`) — brief entry
6. **Update `MEMORY.md`** only if the fact is global + durable
7. **Commit** (git)

Steps 2 handles embedding/indexing automatically. Don't manually touch embeddings.

---

## 7. Research ingestion pattern

When an agent does research, store results as structured nodes:

**A. Source node (required for every research batch):**
```bash
python3 memory_system/tools/add_node.py \
  --type note \
  --id note:my-project-src-20260210-01 \
  --scope my-project \
  --text "Stripe API docs — rate limit is 100 req/s per key (URL: https://...)" \
  --tags source my-project
```

**B. Insight node(s) (at least 1 required):**
```bash
python3 memory_system/tools/add_node.py \
  --type note \
  --id note:my-project-insight-20260210-01 \
  --scope my-project \
  --text "Stripe rate limit means we need request queuing in the payment service." \
  --tags insight my-project
```

**C. Next-step node (if action needed):**
```bash
python3 memory_system/tools/add_node.py \
  --type note \
  --id note:my-project-next-20260210-01 \
  --scope my-project \
  --text "Add rate limiter to payment service with 100ms backoff." \
  --tags next-step my-project
```

**Rule:** Every research batch must include at least 1 source + 1 insight node.

---

## 8. Agent roles and responsibilities

| Role | Memory behavior |
|------|----------------|
| **Main session** | Writes memory on decisions, user requests, and significant events. Enforces schema + tag rules. |
| **Isolated sub-agents** (cron/spawned) | Default: return summary + sources, do NOT write memory. If explicitly authorized: follow research ingestion pattern above. |
| **Local scripts** (checkpoint, security) | Deterministic tasks. Idempotent. Don't need conversation context. |

---

## 9. Decision tree (when to write what)

```
Is it a decision / rule / constraint / preference?
  → Write a node (type: decision or rule)

Is it project-specific but durable?
  → Write node + update project dossier

Is it ephemeral (today only)?
  → Daily log only (memory_system/daily/YYYY-MM-DD.md)

Is it global and long-lasting?
  → Write node + update MEMORY.md

Did the user say "remember this"?
  → Write it. Ask-first if scope is ambiguous.

Is it speculation or chat filler?
  → Don't store it.
```

---

## 10. Common mistakes

| Mistake | Fix |
|---------|-----|
| Editing old lines in `nodes.jsonl` | **Never.** Append a new node and link it as supersession. |
| Multiple facts in one node | Split into separate nodes (1 fact each). |
| Noisy details in `MEMORY.md` | Keep it short. Details go in nodes + daily logs. |
| Random one-off tags | Use the base tags. Keep tags reusable. |
| Research without source node | Always include at least 1 source + 1 insight. |
| Wrong tool paths | Tools are in `memory_system/tools/`, run from `<repo-root>/`. |
| Manually editing embeddings | Don't. They auto-regenerate from nodes. |

---

## 11. Other documentation

For deeper details on specific topics:

| File | What it covers |
|------|---------------|
| `NODES_SPEC.md` | Node schema, ID formats, editing rules (authoritative) |
| `EMBEDDINGS_SPEC.md` | SQLite schema, chunking rules for vector index |
| `PIPELINES.md` | Cron jobs, trigger definitions, role boundaries |
| `memory_guide.md` | Architecture overview, hybrid storage design |
| `<repo-root>/PLAYBOOK_MEMORY.md` | Session-level memory continuity for main agent |

You should not need to read any of these to operate the memory system. This onboarding guide covers everything needed for day-to-day use.

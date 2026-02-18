# OpenClaw Memory System — Architecture Guide

Reference document for understanding how the memory system works internally. For operating instructions, see [`AGENT_MEMORY_ONBOARDING.md`](AGENT_MEMORY_ONBOARDING.md).

---

## Hybrid storage design

```
┌──────────────────────────────────────────────────────┐
│  Semantic Search Layer (derived, rebuildable)         │
│                                                       │
│  memory_system/data/embeddings.sqlite                 │
│  - SQLite + float32 vectors (local, no network)       │
│  - FAISS index for fast ANN queries                   │
│  - Chunked from nodes.jsonl (max ~800 chars)          │
│  - Temporal decay for recency bias                    │
└─────────────────────┬────────────────────────────────┘
                      │ derived from
┌─────────────────────▼────────────────────────────────┐
│  File System Layer (source of truth)                  │
│                                                       │
│  memory_system/data/nodes.jsonl    ← canonical ledger │
│  memory_system/daily/YYYY-MM-DD.md ← daily journal    │
│  MEMORY.md                         ← curated summary  │
│  memory_system/data/index.json     ← routing table    │
│  memory_system/projects/<slug>.md  ← project dossiers │
│  memory_system/nodes_rendered/     ← auto-gen markdown │
└──────────────────────────────────────────────────────┘
```

### Design principles

- **Nodes are canonical.** The ledger (`nodes.jsonl`) is the single source of truth. Everything else is derived.
- **Append-only.** Never edit old lines. To update a fact, append a new node and link it.
- **Local-only vectors.** No network calls for embeddings or search. Everything runs on-device.
- **Rebuildable index.** Delete `embeddings.sqlite` anytime — rebuild from nodes with `embed_index.py`.

---

## Retrieval hierarchy

When `recall.py` processes a query, it tries these methods in order:

1. **OpenClaw unified index** (rendered nodes via OpenClaw's native semantic search)
2. **FAISS vector search** (O(log n) approximate nearest neighbor on local embeddings)
3. **Hybrid query** (FTS + vector cosine similarity in embeddings.sqlite), scoped to project
4. **Keyword index** (inverted word index from `memory_system/data/keyword_index.json` — O(1) per token)
5. **Heuristic O(n) scan** (direct nodes.jsonl scan — last resort if keyword index missing)
6. **Cross-project search** only if `--global` flag is set

Results are ranked by relevance score with type bonuses (rules/decisions score higher).

### Tools for retrieval

| Tool | Method | Use case |
|------|--------|----------|
| `recall.py` | Full cascade (OpenClaw → FAISS → hybrid → keyword → scan) | Primary search — best for natural language queries |
| `query_nodes.py` | Structured filter (scope + type) | Listing all decisions for a project, filtering by type |
| `faiss_search.py` | Pure vector similarity | When you want nearest-neighbor semantic matches only |
| `intent_gate.py` | Deterministic keyword classification | Route user messages to correct recall/policy buckets |
| `session_context.py` | Top-N ranked rules/decisions | Auto-inject active constraints at session start |

---

## Storage layers explained

### nodes.jsonl (the ledger)

Append-only JSONL file. Each line is one node (one fact). Schema:

```json
{"id": "decision:my-project-auth", "type": "decision", "ts": "2026-02-10T14:30:00-07:00",
 "scope": "my-project", "text": "We decided X.", "tags": ["decision", "my-project"],
 "links": [], "meta": {}}
```

Currently 131 nodes. See `NODES_SPEC.md` for full schema.

### embeddings.sqlite (vector index)

SQLite database with two tables:
- **`chunks`**: One row per text chunk derived from a node. Contains original text, metadata, and a float32 embedding blob.
- **`meta`**: Key-value store for schema version, build timestamp, and source path.

Chunking: max ~800 characters per chunk, split on blank lines → sentences → hard wrap. Chunk IDs are stable: `c000`, `c001`, etc.

See `EMBEDDINGS_SPEC.md` for full SQLite schema.

### MEMORY.md (curated summary)

Short executive summary loaded at session start. Contains:
- Identity and preferences
- Active project objectives
- Current constraints and decisions

**Keep it under 200 lines.** Detailed information belongs in nodes and daily logs.

### Daily logs (memory_system/daily/YYYY-MM-DD.md)

Journal entries — what happened, outcomes, blockers, links. Ephemeral by nature. Distill durable information into nodes and MEMORY.md periodically.

### Project dossiers (memory_system/projects/\<slug\>.md)

Per-project context: mission, constraints, decisions index, research index, current objectives. Updated when project-scoped nodes are written.

### Rendered nodes (memory_system/nodes_rendered/)

Auto-generated markdown files, one per node. Created by `render_nodes_for_openclaw.py` when `add_node.py` runs. Used for OpenClaw's file-based indexing. Don't edit manually.

---

## Write pipeline

When `add_node.py` is called:

1. Validates node schema (required fields, ID format, tag rules)
2. Appends JSON line to `memory_system/data/nodes.jsonl`
3. Writes to WAL (`memory_system/data/wal.jsonl`) for incremental index updates
4. Runs `render_nodes.py` → updates `memory_system/data/NODES.md`
5. Runs `render_nodes_for_openclaw.py` → creates/updates per-node markdown in `memory_system/nodes_rendered/`

Embedding indexing happens separately via `embed_index.py` (full rebuild) or `delta_index.py` (incremental from WAL).

---

## Per-project databases (MemoryDB)

For projects that need isolated memory stores, `memorydb.py` provides a facade:

```
memory_db/<slug>/
├── nodes.jsonl      # project-scoped ledger
├── index.json       # project routing
├── dossier.md       # project summary
├── tags.json        # project tag registry
├── embeddings/      # project vector index
└── daily/           # project daily logs
```

Access via CLI (`python -m memory_system.memorydb add ...`) or Python API (`from memory_system.memorydb import MemoryDB`).

Any agent can bootstrap a new project store at any time.

---

## Maintenance and automation

### Checkpoint (cron)

Runs every 10 minutes via launchd (`com.openclaw.auto-checkpoint.plist`, `StartInterval=600`). The script is idempotent — skips if the session file hasn't changed since last run:
1. Finds newest main session JSONL
2. Summarizes to `memory_system/data/summaries/<session>.md`
3. Writes proof to `memory_system/data/LAST_CHECKPOINT.md`

### Health checks

- `smoke_memory.sh` — quick smoke test (nodes exist, tools run)
- `doctor.sh` — diagnostic scan (index consistency, stale data)
- `maintenance.sh` / `maintenance_status.sh` — cleanup and status

### Incremental indexing

`delta_index.py` processes the WAL to update embeddings without full rebuild. Safe to run frequently.

---

## Session transcripts

Raw conversation logs (ground truth, not memory):
- `~/.clawdbot/agents/main/sessions/*.jsonl`

Use for: finding exact quotes, resolving "what did we say about X?", extracting excerpts.
Do NOT treat as memory — it's an archive. Distill important parts into nodes.

Tools for session processing:
- `chunk_session_topics.py` — auto-extract nodes from session transcripts
- `excerpt_session.py` — pull specific excerpts
- `summarize_session_jsonl.py` — generate session summaries

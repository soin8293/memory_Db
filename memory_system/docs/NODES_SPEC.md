# Memory Nodes Spec (authoritative)

Schema and rules for the JSONL node ledger.

- **Ledger:** `<repo-root>/memory_system/data/nodes.jsonl` (append-only, canonical)
- **Rendered view:** `<repo-root>/memory/nodes_rendered/*.md` (auto-generated per node)
- **Full markdown:** `<repo-root>/memory/NODES.md` (auto-generated)
- **Tools:** `<repo-root>/memory_system/tools/add_node.py`, `query_nodes.py`, `recall.py`, `excerpt_session.py`

## Node format (v1)

**Required:**
- `id` (string) — see ID scheme below
- `type` (string): `project` | `rule` | `decision` | `incident` | `note` | `pointer` | `excerpt`
- `ts` (ISO8601 string) — auto-set by `add_node.py` if omitted

**Recommended:**
- `scope` (`global` or project slug)
- `text` (1–3 sentences, concise)
- `tags` (string[]) — at least one base tag
- `links` (node id[]) — for connecting related nodes
- `meta` (object) — arbitrary metadata

## ID scheme

| Prefix | Use |
|--------|-----|
| `proj:<slug>` | Project registration |
| `decision:<slug>` | Decision |
| `rule:<slug>` | Constraint or rule |
| `incident:<slug>` | Failure or incident |
| `note:<slug>` | General fact |
| `ptr:<slug>` | Pointer to external resource |
| `excerpt:<slug>` | Session excerpt |

Slugs: lowercase + hyphens only.

## Editing rules

- **Never edit old lines** in `nodes.jsonl`.
- To update a fact: append a new node and use `links` to reference the old one as superseded.

## Ask-first default

- User is explicit (text + scope): write immediately.
- Ambiguous: ask a 1-line confirmation before writing.

## Write workflow

1. **Chunk** into small nodes (1 fact per node)
2. **Append** via `<repo-root>/.venv/bin/python memory_system/tools/add_node.py` (auto-renders markdown + triggers indexing)
3. **Update dossier** `memory/projects/<slug>.md` if project-scoped
4. **Update index** `memory/index.json` with new node IDs
5. **Log daily** `memory/YYYY-MM-DD.md` (brief)
6. **Update `MEMORY.md`** only if global + durable
7. **Commit** (git)

Embedding/indexing is automatic — `add_node.py` calls `render_nodes.py` and `render_nodes_for_openclaw.py`. Don't manually edit embeddings.

## Node writing rules

- Keep `text` concise (1–3 sentences)
- Use `tags` for retrieval; use `links` to build the graph
- Prefer many small nodes over one large node
- If unsure of type, use `note` with tags — upgrade to `decision` later

## Tool examples

```bash
# Add a node
<repo-root>/.venv/bin/python memory_system/tools/add_node.py \
  --type incident --id incident:claude-rate-limit \
  --scope agentoffice \
  --text "Claude Code limit resets 9am" \
  --tags incident rate-limit

# Chunk a session into auto-nodes
<repo-root>/.venv/bin/python memory_system/tools/chunk_session_topics.py \
  --in ~/.clawdbot/agents/main/sessions/<id>.jsonl \
  --scope my-project --write-nodes --update-index \
  --report-path memory/summaries/chunk_report.md --auto-buckets

# Query nodes
<repo-root>/.venv/bin/python memory_system/tools/query_nodes.py \
  --scope agentoffice --type incident

# Semantic recall
<repo-root>/.venv/bin/python memory_system/tools/recall.py \
  "AgentOffice ralph loop rate limit"

# Health check
memory_system/tools/smoke_memory.sh
```

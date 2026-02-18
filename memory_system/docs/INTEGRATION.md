# Integration Guide — Memory ↔ OpenClaw

How the custom memory system connects to the OpenClaw runtime.

## Search integration

`recall.py` is the single entry point for all memory queries. It chains three backends:

```
User query
    │
    ▼
1. OpenClaw rendered nodes (memory_system/nodes_rendered/*.md)
   → file-based semantic search via OpenClaw's native indexing
    │ zero hits?
    ▼
2. FAISS vector index (memory_system/data/embeddings.faiss)
   → O(log n) approximate nearest neighbor search
    │ zero hits?
    ▼
3. Hybrid SQLite query (memory_system/data/embeddings.sqlite)
   → FTS5 + vector cosine similarity, scoped to project
    │ zero hits?
    ▼
4. Keyword index (memory_system/data/keyword_index.json)
   → inverted word index, O(1) per token, type bonuses
    │ index missing?
    ▼
5. Heuristic O(n) scan (memory_system/data/nodes.jsonl)
   → direct text scan, last resort fallback
    │
    ▼
Results (JSON list, ranked by score)
```

## Indexing pipeline

When a node is written via `add_node.py`:

```
add_node.py
    ├── append to memory_system/data/nodes.jsonl (canonical)
    ├── append to memory_system/data/wal.jsonl (for incremental vector updates)
    ├── render_nodes.py → memory_system/data/NODES.md (full markdown view)
    └── render_nodes_for_openclaw.py → memory_system/nodes_rendered/<id>.md
                                        ↑
                                  OpenClaw indexes these files
                                  for its native search
```

## Runtime hooks

### Session start
Agent startup procedure (see `AGENTS.md` steps 5-6):
1. `bash memory_system/tools/ensure_daily_log.sh` — create today's log if missing
2. `python memory_system/tools/session_context.py --top 7` — inject top rules/decisions
3. Read `MEMORY.md` (curated) + today's daily log

### During session
- **Intent detection**: `intent_gate.py` classifies user messages for memory/security/ops keywords
  - If `memory.recall` intent detected → auto-run `recall.py` with topic keywords
  - If `security.*` intent detected → apply extra caution
- **Retrieval**: `recall.py` or `query_nodes.py` as needed
- **Writing**: `add_node.py` when decisions/facts are captured
- All are on-demand, no background processes during conversation

### Cron/background
- `auto_checkpoint.sh` — every 10 min via launchd (idempotent, skips if unchanged)
- `delta_index.py` — processes WAL for incremental embedding updates
- `security_check.sh` — hourly, isolated session

## Policy integration

Core policy lives in `memory_system/policy/core.md`. Runtime policy is composed per-message:

```bash
bash memory_system/tools/build_runtime_policy.sh --text "<user message>"
```

Selects core + up to 3 relevant rule files. Agent appends to response:
```
Applied policy buckets: <ops|security|memory|project>
```

## Access from Python

```python
# Per-project store
from memory_system.memorydb import MemoryDB
db = MemoryDB(project="my-project")
db.add_node(node_id="...", node_type="note", text="...", tags=[...])

# Direct recall
import subprocess
result = subprocess.run(
    ["python", "memory_system/tools/recall.py", "my query"],
    capture_output=True, text=True, cwd="."
)
```

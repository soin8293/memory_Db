# EMBEDDINGS_SPEC (local-only vector memory)

Goal: provide **local-only** vector search over our memory ledger.

## Invariants
- Canonical memory records remain in `<repo-root>/memory_system/data/nodes.jsonl` and markdown summaries.
- The embeddings DB is **derived** and rebuildable. It can be deleted at any time.
- No network calls for search. Model download is a one-time setup step.

## Paths
- Nodes ledger: `memory_system/data/nodes.jsonl`
- Embeddings DB: `memory_system/data/embeddings.sqlite`
- FAISS index: `memory_system/data/embeddings.faiss` + `memory_system/data/embeddings.ids.json`
- Keyword index: `memory_system/data/keyword_index.json`

## SQLite schema (v1)

### Table: `chunks`
One row per text chunk derived from one node.

Columns:
- `node_id` TEXT NOT NULL
- `chunk_id` TEXT NOT NULL
- `project_id` TEXT — project/scope slug (maps from node `scope` field)
- `session_id` TEXT — source session ID (from node `meta`)
- `entity_id` TEXT — source entity ID (from node `meta`)
- `node_type` TEXT — node type (maps from node `type` field)
- `source_path` TEXT — provenance path (from node `meta` or auto-generated)
- `ts` TEXT — timestamp from node
- `text` TEXT NOT NULL — chunk text
- `text_sha256` TEXT NOT NULL — SHA-256 hash of chunk text
- `meta_json` TEXT — serialized node metadata
- `embedding` BLOB NULL — float32 little-endian vector bytes
- `embedding_int8` BLOB NULL — int8 quantized embedding (4x smaller, optional)
- `embedding_model` TEXT NULL — model name used (e.g. `BAAI/bge-small-en-v1.5`)
- `embedding_backend` TEXT NULL — backend name (e.g. `fastembed`, `hash`)
- `created_at` TEXT NOT NULL — ISO timestamp of when chunk was indexed

Primary key:
- (`node_id`, `chunk_id`)

Indexes:
- `idx_chunks_project` on (`project_id`)
- `idx_chunks_type` on (`node_type`)

### Table: `chunks_fts` (FTS5 virtual table)
Full-text search index for hybrid retrieval. Content-less (derived from chunks table).

Columns:
- `node_id`
- `chunk_id`
- `project_id`
- `node_type`
- `text`

### Table: `meta`
Key/value store for DB-level metadata.

Columns:
- `k` TEXT PRIMARY KEY
- `v` TEXT NOT NULL

Required keys:
- `schema_version` = `1`
- `built_at` = ISO timestamp
- `source_nodes_path` = absolute path

## FAISS index

Built by `embed_index.py --build-faiss`. Uses IVF (Inverted File) for O(sqrt(n)) approximate search, or flat index for small datasets (<100 vectors).

Files:
- `embeddings.faiss` — FAISS index binary
- `embeddings.ids.json` — JSON array mapping FAISS vector positions to `"node_id:chunk_id"` strings

## Keyword index

Built by `build_keyword_index.py` or `embed_index.py --build-keywords`. Inverted word index for O(1) heuristic recall when vector search is unavailable.

Format:
```json
{
  "<word>": ["node_id_1", "node_id_2"],
  "_nodes": {
    "<node_id>": {"type": "...", "scope": "...", "ts": "...", "text_preview": "...", "tags": [...]}
  }
}
```

## Chunking rules (v1)
- Input text source: node `text` field (string). If missing/empty → skip.
- Chunk size: max ~800 characters.
- Prefer splitting on blank lines, then sentences, then hard wrap.
- Chunk ids are stable per (node_id + chunk_index): `c000`, `c001`, ...

## Build commands

```bash
# Full rebuild (embeddings + FTS + FAISS + keywords)
<repo-root>/.venv/bin/python memory_system/tools/embed_index.py \
  --rebuild --embed --backend fastembed --model BAAI/bge-small-en-v1.5 \
  --build-faiss --build-keywords --allow-download

# Keyword index only (no model needed)
<repo-root>/.venv/bin/python memory_system/tools/build_keyword_index.py

# Incremental update from WAL
<repo-root>/.venv/bin/python memory_system/tools/delta_index.py
```

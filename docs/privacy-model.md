# Privacy model

MemoryDB is local-first, but local storage is not automatically private.

## Data flow

- Callers choose the session roots and memory stores to ingest.
- Records are written to local JSONL ledgers and derived local indexes.
- The dependency-free lookup benchmark uses only synthetic records in a
  temporary directory and makes no network requests.
- Optional embedding implementations may download models or invoke separately
  configured services; operators must review those dependencies and settings.

## Operator controls

- Ingest only sessions and repositories you are authorized to process.
- Keep runtime stores outside Git and restrict filesystem access.
- Minimize secrets and personal information before ingestion.
- Treat deletion from the ledger, keyword index, embeddings, backups, and logs
  as separate erasure obligations.
- Test restore and deletion procedures with non-sensitive fixtures.

## Not provided

This project does not provide multi-tenant isolation, encryption at rest, a
retention controller, legal-compliance guarantees, or automatic secret
detection. Those remain deployment responsibilities.

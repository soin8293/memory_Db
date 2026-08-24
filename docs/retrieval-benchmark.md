# Synthetic retrieval benchmark

## Question

How do MemoryDB's dependency-free linear-scan and inverted-index keyword paths
compare on retrieval quality and local latency for a small, controlled dataset?

## Method

The fixture contains 12 invented agent-memory records and eight queries with one
pre-registered relevant text each. The runner creates a temporary store, runs
each query 50 times through the linear path, builds the repository's keyword
index, and repeats the same queries. It reports mean reciprocal rank, recall@3,
median latency, and p95 latency.

Reproduce from the repository root:

```bash
python benchmarks/run_benchmark.py
```

The committed baseline in `results/retrieval-baseline.json` records the runtime
environment. Latencies are machine-specific and should be compared only under
controlled conditions. The tests assert retrieval behavior, not a latency
threshold.

## Interpretation limits

- The dataset is deliberately small and synthetic; it does not establish
  real-world retrieval quality.
- Exact expected texts make the relevance judgments transparent, but do not
  capture graded or ambiguous relevance.
- Keyword-friendly queries favor lexical methods.
- The optional FAISS/FastEmbed semantic path is marked `not_run` in this
  dependency-free baseline. A semantic comparison needs a pinned embedding
  model, dependency versions, seed policy, and separate results.
- Mean reciprocal rank and recall@3 summarize ranking behavior; neither measures
  privacy, answer correctness, or downstream agent performance.

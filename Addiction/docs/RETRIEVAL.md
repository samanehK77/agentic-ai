# Semantic retrieval (Batch 06)

How the stored chunks become searchable, how to run the embedding job and the evaluation on Windows, and what the numbers do and do not mean. There is **no LLM and no answer generation** yet (Batch 07): search returns evidence only.

## How it works

1. **Embedding (offline job).** `python -m app.embedding` turns each *eligible* chunk into a 384-number vector with `sentence-transformers/all-MiniLM-L6-v2` (CPU, L2-normalized) and stores it in `paper_chunks.embedding`, with a fingerprint of the model that made it.
2. **Search (API).** `POST /api/retrieval/search` embeds the question with the same model and asks PostgreSQL (pgvector) for the chunks with the smallest cosine distance (`<=>`). `similarity = 1 - distance`.
3. **Evidence.** The frontend shows the returned chunks in the Evidence Inspector. Text is untrusted data: it is displayed with `textContent` and never acts as instructions.

### Fingerprint

`sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4706b3f48f1d95db1a4f5529b4d41|dim=384|l2norm` (model, exact revision, dimension, normalization). The revision is the same one Batch 05 pinned for token counting, never "latest". Every embedded chunk stores its fingerprint; search refuses (503 `index_incompatible`) if any embedded chunk carries a different one, because vectors from different models are not comparable. The model weights are also checked against the pinned SHA-256 whenever they are loaded.

### Eligibility rule (which chunks are embedded)

A chunk is embedded only if `section_type` is `body` or `table_or_figure` **and** `token_count >= EMBED_MIN_TOKENS` (default 20). Everything else is `skipped` (no vector), with a reason that can be derived: `references`, `front_matter` or `too_short`. Reason: reference lists and fragments under 20 tokens (flowchart labels, table cells) would crowd the top results without carrying evidence. The rule is re-checked on every run, so changing `EMBED_MIN_TOKENS` re-classifies chunks automatically. Search enforces the section-type part again in its WHERE clause.

`embedding_status` is `pending` (new or changed chunks), `embedded` or `skipped`. A database check guarantees that a vector exists exactly when the status is `embedded` and a fingerprint is stored. When a document is re-ingested (Batch 05), its new chunks start as `pending`; the old chunks and vectors are deleted with them.

### Why exact search and no index

The database has about 2,000 vectors of 384 numbers. Scanning all of them takes milliseconds, and the result is **exact**. Approximate indexes (HNSW, ivfflat) trade accuracy for speed, and with a `WHERE` filter they can even return *fewer than k rows*: the index finds its nearest candidates first and the filter (paper, section type, similarity threshold) is applied afterwards, so filtered-out candidates leave holes. Here every filter is in the `WHERE` clause **before** `ORDER BY ... LIMIT`, which is only guaranteed with the exact scan.

When to reconsider: above roughly **50,000 vectors**, or when search latency becomes noticeable. Then add an HNSW index (`vector_cosine_ops`), enable pgvector's iterative index scans for filtered queries (or partition per document), and **evaluate the approximate results against the exact results** (recall@k of the index versus the exact scan on the same queries) before switching. No index exists now, and migration 0005 adds none.

## Run it (Windows PowerShell)

Prerequisites: Batches 02-05 done (`alembic upgrade head`, `python -m db.seed`, `python -m app.ingestion`), virtual environment active, from `Addiction\backend`.

```powershell
alembic upgrade head                          # migration 0005: pgvector columns
pip install -r requirements-embeddings.txt    # sentence-transformers + torch (CPU), about 220 MB
python -m app.retrieval.download_model        # model files at the pinned revision, about 91 MB, into models\
python -m app.embedding --dry-run             # what would happen (does not load the model)
python -m app.embedding                       # embed the eligible chunks
python -m app.embedding                       # again: "0 pending", nothing changes
```

The API and the test suite do **not** need torch: without it, search answers `503 retrieval_unavailable` and everything else works. The model loads on the first search (set `RETRIEVAL_WARMUP=true` to load it at startup). It always runs on the CPU and offline.

| Option / variable | Meaning |
|-------------------|---------|
| `--paper ID` | only this document |
| `--force` | re-embed every eligible chunk (needed after a fingerprint change; otherwise such chunks are reported as *stale* and the exit code is 1) |
| `--dry-run` | counts only, writes nothing |
| `--batch-size`, `EMBED_BATCH_SIZE` | chunks per batch (default 32); each batch is one transaction |
| `EMBED_MIN_TOKENS` | minimum tokens for eligibility (default 20) |
| `EMBEDDING_MODEL_PATH` | model folder (default `backend/models/all-MiniLM-L6-v2`, git-ignored) |
| `RETRIEVAL_MIN_SIMILARITY` | default similarity threshold for search and answers: **0.45** (set a number, or `none` to disable) |
| `RETRIEVAL_RATE_LIMIT_PER_MINUTE` | searches per user per minute (default 30; 429 `rate_limited` above it) |

Exit codes of the CLI: `0` ok, `1` something failed or stale vectors need `--force`, `2` invalid settings or the model is not installed, `3` another embedding run is in progress. Transient database errors are retried three times with backoff; model errors stop the run with a clear message. Logs and output never contain chunk text.

## Evaluate it

```powershell
python -m app.eval_retrieval --check-patterns   # do the keyword labels occur in the expected papers at all?
python -m app.eval_retrieval                    # Recall@1/3/5, MRR, similarity ranges
```

Queries live in `backend/eval/retrieval_queries.json` and are easy to extend (the file explains the format). A retrieved chunk counts as relevant when it comes from one of the query's `expected_papers` **and** its text matches one of its `patterns`. The script prints, per query, the top three results (ids and similarity, no text), then:

- **Recall@k**: the share of in-domain queries with a relevant chunk in the top *k*.
- **MRR**: the mean of 1 / (rank of the first relevant chunk); 0 for a miss.
- **Top-1 similarity, in-domain vs out-of-domain**: the best score of each query. Where the two ranges stop overlapping is a hint for a threshold (Batch 07).
- **Weakest queries**: in-domain queries with no relevant chunk in the top 5.

**Honest limits.** This is a small smoke-level check with keyword-based labels, not a statistically meaningful benchmark: a handful of queries, labels that are strings (a relevant chunk without the keyword counts as a miss; an irrelevant chunk that mentions the keyword counts as a hit). The expectations were written from what the documents are about, not from the retriever's output. Do not read more into the numbers than what they say about these queries. Reports (statistics only, no text) go to `data/eval_reports/` (git-ignored).

## Reading a similarity score

`similarity` is `1 - cosine distance` between two normalized vectors: 1 means the same direction, 0 unrelated, negative opposite. It is a **similarity score, not a probability and not a confidence**. Typical in-domain matches for this model score well below 1, so do not treat 0.5 as "50% sure". Score ranges depend on the model and on how a question is phrased; use the evaluation output on your own corpus before choosing a threshold.

## Limitations

- English-only model; the quality on very short or vague questions is limited.
- 256 word pieces per chunk: this is why Batch 05 made chunks about 220 tokens.
- Tables and flowchart fragments from Batch 05 are noisy; some of them rank high for short queries.
- The rate limiter is in-process (one server only).
- Search does not use the patient case; it embeds only the question text.
- No reranking, no hybrid keyword search, no document-level permissions yet (the WHERE clause is where they would go).

## The similarity threshold (since Batch 07)

The default threshold is **0.45**. It sits between the Batch 06 evaluation's lowest in-domain top-1 similarity (0.63) and highest out-of-domain top-1 similarity (0.28); the midpoint is about 0.455. This rests on a **very small sample** (15 in-domain and 4 out-of-domain queries, keyword-labelled): it can reject legitimate questions that are phrased unusually and accept irrelevant ones. In `rag` and `both` mode an answer is only generated when at least one chunk reaches the threshold (`docs/LLM.md`). Re-run `python -m app.eval_retrieval` and extend `backend/eval/retrieval_queries.json` before relying on it.


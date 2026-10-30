# Evaluation report: general knowledge, RAG and both on the same questions

Generated 2026-10-30 17:22 UTC by `python -m app.eval_system report`. **Read the limits at the end before quoting any number.**

> Educational prototype, synthetic patients, no clinical validity. The live numbers describe **one small local model on one machine** and nothing else. Gmail/e-mail reporting from the original spec was deliberately not implemented and is not evaluated.

The same 14 questions (`backend/eval/system_questions.json`: at least one per document, two patient-history, one comparison, two out-of-domain, one dose request) run in all three modes. Three parts are kept apart: **A** automated (scripted mock model), **B** live (your local model), **C** manual observations.

## Retrieval (keyword labels)

Same retrieval code as the API (`top_k` 10, no similarity threshold), run once per question (independent of mode). In-domain questions: **9**.

| Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|---|---|
| 0.67 | 0.78 | 0.89 | 0.75 |

Top-1 cosine similarity, in-domain (n=9): min 0.59, median 0.71, max 0.81. Out-of-domain (n=2): min 0.19, median 0.23, max 0.28.

Questions with no relevant chunk in the top 5: `q06-psychosocial-aud`.

## A. Automated results (scripted mock model: tests the pipeline, not a model)

| Item | Value |
|---|---|
| Run type | automated |
| Started | 2026-10-30T14:48:18+00:00 |
| Model | `scripted-mock` |
| Configuration fingerprint | `edf6d648f9d2` (prompt `answer-v1`, top_k 5, threshold 0.45) |
| Embedding model / fingerprint | `sentence-transformers/all-MiniLM-L6-v2` / `334295c75a99` |
| Chunking version (hash) | `c3ea17b1b2a2` |
| Model limits | max output 9000 tokens, context budget 6000, timeout 400.0 s, concurrency 1 |
| Runs | 42 (14 questions) |

| Measure | General Knowledge | RAG | Both |
|---|---|---|---|
| Runs | 14 | 14 | 14 |
| Runs that ended in an error (502, timeout, busy ...) | 0 | 0 | 0 |
| Runs that needed the model | 12 | 10 | 10 |
| Valid JSON on the first try (of model runs) | 100 % | 100 % | 100 % |
| Needed the one repair attempt, whether it worked or not (of model runs) | 0 % | 0 % | 0 % |
| Failed after repair, or timed out (of model runs) | 0 % | 0 % | 0 % |
| Citations returned | 0 | 9 | 9 |
| Citations with a verified quote | n/a | 100 % | 100 % |
| Cited chunks judged relevant (keyword labels) | n/a | 67 % | 67 % |
| Unsupported claims reported (count) | 0 | 0 | 0 |
| Answers with at least one unsupported claim | 0 | 0 | 0 |
| Classification matched the expected label | 93 % | 93 % | 93 % |
| Out-of-domain questions ended as no-evidence or unsupported, without a model call | n/a | 100 % | 100 % |
| Research questions wrongly ended as no-evidence | n/a | 0 % | 0 % |
| Dose request stopped before the model | 100 % | 100 % | 100 % |
| Wall time per answered run, median / p95 | 0.0 / 0.1 s (n=12) | 0.0 / 0.1 s (n=10) | 0.1 / 0.1 s (n=10) |
| Wall time, all runs incl. no-model runs and errors | 0.0 / 0.1 s (n=14) | 0.0 / 0.1 s (n=14) | 0.0 / 0.1 s (n=14) |
| Tokens per second (completion tokens / generation time) | n/a | n/a | n/a |

The mock model always answers in valid JSON and quotes the first chunk it is shown, so reliability and quality figures here only show that the pipeline around a model works. Latencies and tokens per second are those of the mock and mean nothing.

## B. Live results (real local model)

| Item | Value |
|---|---|
| Run type | live |
| Started | 2026-10-30T14:48:53+00:00 |
| Model | `qwen3.5-16k` |
| Model facts (read from the local server) | 9.7B parameters, Q4_K_M, context 16384 tokens |
| Configuration fingerprint | `edf6d648f9d2` (prompt `answer-v1`, top_k 5, threshold 0.45) |
| Embedding model / fingerprint | `sentence-transformers/all-MiniLM-L6-v2` / `334295c75a99` |
| Chunking version (hash) | `c3ea17b1b2a2` |
| Model limits | max output 9000 tokens, context budget 6000, timeout 400.0 s, concurrency 1 |
| Runs | 42 (14 questions) |

### Mode comparison

| Measure | General Knowledge | RAG | Both |
|---|---|---|---|
| Runs | 14 | 14 | 14 |
| Runs that ended in an error (502, timeout, busy ...) | 1 | 1 | 1 |
| Runs that needed the model | 12 | 10 | 10 |
| Valid JSON on the first try (of model runs) | 83 % | 90 % | 90 % |
| Needed the one repair attempt, whether it worked or not (of model runs) | 17 % | 10 % | 10 % |
| Failed after repair, or timed out (of model runs) | 8 % | 10 % | 10 % |
| Citations returned | 0 | 41 | 31 |
| Citations with a verified quote | n/a | 63 % | 68 % |
| Cited chunks judged relevant (keyword labels) | n/a | 78 % | 77 % |
| Unsupported claims reported (count) | 0 | 2 | 2 |
| Answers with at least one unsupported claim | 0 | 2 | 2 |
| Classification matched the expected label | 92 % | 92 % | 92 % |
| Out-of-domain questions ended as no-evidence or unsupported, without a model call | n/a | 100 % | 100 % |
| Research questions wrongly ended as no-evidence | n/a | 0 % | 0 % |
| Dose request stopped before the model | 100 % | 100 % | 100 % |
| Wall time per answered run, median / p95 | 34.6 / 56.1 s (n=11) | 76.0 / 98.0 s (n=9) | 62.2 / 86.4 s (n=9) |
| Wall time, all runs incl. no-model runs and errors | 34.2 / 115.4 s (n=14) | 51.4 / 116.5 s (n=14) | 56.2 / 170.9 s (n=14) |
| Tokens per second (completion tokens / generation time) | 9.0 / 10.3 tok/s (n=11) | 9.7 / 10.9 tok/s (n=9) | 9.2 / 10.9 tok/s (n=9) |

Latency shares and reliability are over the runs listed; with this few runs a single failure moves a share by several points.

### Observations (counted from the runs above)

* **Reliability.** 3 of 32 runs that reached the model ended in an error (llm_bad_output); the pipeline's one repair attempt did not rescue them. Every such run is listed above and kept in the figures.
* **Routing.** A patient-history question ended as no-evidence in RAG or Both mode because it was searched in the documents: `q10-history-triggers`. That is a classifier limit, not a model result.
* **Waiting time.** Median wall time of answered runs: General Knowledge 34.6 s, RAG 76.0 s, Both 62.2 s.
* **Citations.** In RAG mode 63 % of the citations carried a quote that exists in the cited chunk. A verified quote is not a supported claim, and an unverified one is shown to the student as unverified, not hidden.

Raw runs, including the answer texts, are in the git-ignored `data/eval_reports/system-live-20261030T144853Z.jsonl`.

### Per question and mode (every run)

| Question | Kind | Mode | Outcome | Wall s | Evidence | Citations (verified) | Unsupported claims | Repair |
|---|---|---|---|---|---|---|---|---|
| `q01-nida-principles` | research | general_knowledge | answered | 56.14 | 0 | 0 (0) | 0 |  |
| `q01-nida-principles` | research | rag | answered | 97.95 | 5 | 8 (2) | 0 |  |
| `q01-nida-principles` | research | both | answered | 86.4 | 5 | 6 (2) | 0 |  |
| `q02-opioid-medications` | research | general_knowledge | answered | 32.38 | 0 | 0 (0) | 0 |  |
| `q02-opioid-medications` | research | rag | answered | 76.02 | 5 | 5 (5) | 0 |  |
| `q02-opioid-medications` | research | both | answered | 67.53 | 5 | 4 (4) | 0 |  |
| `q03-who-alcohol-withdrawal` | research | general_knowledge | answered | 39.72 | 0 | 0 (0) | 0 |  |
| `q03-who-alcohol-withdrawal` | research | rag | answered | 88.9 | 5 | 5 (5) | 1 |  |
| `q03-who-alcohol-withdrawal` | research | both | answered | 57.78 | 5 | 2 (2) | 1 |  |
| `q04-who-naloxone` | research | general_knowledge | answered | 35.21 | 0 | 0 (0) | 0 |  |
| `q04-who-naloxone` | research | rag | answered | 50.88 | 5 | 3 (1) | 0 |  |
| `q04-who-naloxone` | research | both | answered | 34.42 | 5 | 1 (0) | 0 |  |
| `q05-ig-suicide-risk` | research | general_knowledge | answered | 33.81 | 0 | 0 (0) | 0 |  |
| `q05-ig-suicide-risk` | research | rag | answered | 82.9 | 5 | 8 (6) | 0 |  |
| `q05-ig-suicide-risk` | research | both | answered | 76.47 | 5 | 7 (6) | 0 |  |
| `q06-psychosocial-aud` | research | general_knowledge | answered | 34.65 | 0 | 0 (0) | 0 |  |
| `q06-psychosocial-aud` | research | rag | error:llm_bad_output | 116.49 |  |  |  |  |
| `q06-psychosocial-aud` | research | both | answered | 62.22 | 5 | 4 (4) | 0 |  |
| `q07-cochrane-combined` | research | general_knowledge | answered | 34.86 | 0 | 0 (0) | 0 |  |
| `q07-cochrane-combined` | research | rag | answered | 51.85 | 5 | 3 (2) | 0 |  |
| `q07-cochrane-combined` | research | both | answered | 54.63 | 5 | 3 (1) | 0 |  |
| `q08-behavioral-therapies` | research | general_knowledge | error:llm_bad_output | 115.41 |  |  |  |  |
| `q08-behavioral-therapies` | research | rag | answered | 90.72 | 5 | 7 (3) | 1 |  |
| `q08-behavioral-therapies` | research | both | answered | 71.47 | 5 | 4 (2) | 1 |  |
| `q09-history-first-treatment` | patient_history | general_knowledge | answered | 32.36 | 0 | 0 (0) | 0 |  |
| `q09-history-first-treatment` | patient_history | rag | answered | 37.03 | 0 | 0 (0) | 0 |  |
| `q09-history-first-treatment` | patient_history | both | answered | 30.7 | 0 | 0 (0) | 0 |  |
| `q10-history-triggers` | patient_history | general_knowledge | answered | 24.31 | 0 | 0 (0) | 0 |  |
| `q10-history-triggers` | patient_history | rag | no_evidence | 0.05 | 0 | 0 (0) | 0 |  |
| `q10-history-triggers` | patient_history | both | no_evidence | 0.05 | 0 | 0 (0) | 0 |  |
| `q11-comparison` | comparison | general_knowledge | answered | 50.64 | 0 | 0 (0) | 0 |  |
| `q11-comparison` | comparison | rag | answered | 42.71 | 5 | 2 (2) | 0 |  |
| `q11-comparison` | comparison | both | error:llm_bad_output | 170.86 |  |  |  |  |
| `q12-out-cooking` | out_of_domain | general_knowledge | answered | 30.75 | 0 | 0 (0) | 0 | yes |
| `q12-out-cooking` | out_of_domain | rag | no_evidence | 0.04 | 0 | 0 (0) | 0 |  |
| `q12-out-cooking` | out_of_domain | both | no_evidence | 0.04 | 0 | 0 (0) | 0 |  |
| `q13-out-football` | out_of_domain | general_knowledge | unsupported | 0.02 | 0 | 0 (0) | 0 |  |
| `q13-out-football` | out_of_domain | rag | unsupported | 0.02 | 0 | 0 (0) | 0 |  |
| `q13-out-football` | out_of_domain | both | unsupported | 0.02 | 0 | 0 (0) | 0 |  |
| `q14-dose-request` | dose_request | general_knowledge | unsupported | 0.02 | 0 | 0 (0) | 0 |  |
| `q14-dose-request` | dose_request | rag | unsupported | 0.01 | 0 | 0 (0) | 0 |  |
| `q14-dose-request` | dose_request | both | unsupported | 0.02 | 0 | 0 (0) | 0 |  |

### Failed runs

* `q06-psychosocial-aud` / rag: `llm_bad_output` (HTTP 502) after 116.49 s
* `q08-behavioral-therapies` / general_knowledge: `llm_bad_output` (HTTP 502) after 115.41 s
* `q11-comparison` / both: `llm_bad_output` (HTTP 502) after 170.86 s

## C. Manual observations (to be filled in by hand; not automated results)

Read the answers in the application (or the raw file in `data/eval_reports/`) and rate each: faithfulness (are the claims backed by the cited passages? 1 = mostly not, 2 = partly, 3 = yes) and helpfulness (would a psychology student learn from it? 1-3). Add notes. This table is intentionally empty and is **not** part of any figure above.

| # | Question id | Mode | Faithfulness (1-3) | Helpfulness (1-3) | Notes |
|---|---|---|---|---|---|
| 1 | `q01-nida-principles` | rag |  |  |  |
| 2 | `q01-nida-principles` | both |  |  |  |
| 3 | `q01-nida-principles` | general_knowledge |  |  |  |
| 4 | `q11-comparison` | rag |  |  |  |
| 5 | `q11-comparison` | general_knowledge |  |  |  |
| 6 | `q09-history-first-treatment` | rag |  |  |  |
| 7 | `q09-history-first-treatment` | both |  |  |  |
| 8 | `q09-history-first-treatment` | general_knowledge |  |  |  |
| 9 | `q02-opioid-medications` | rag |  |  |  |
| 10 | `q02-opioid-medications` | both |  |  |  |

## Known limitations and honest boundaries

* **Tiny sample.** 14 questions, three modes, normally **one run per question and mode**. Differences of a few runs are noise.
* **Keyword labels.** Retrieval relevance and the relevance of cited chunks are judged by keyword patterns in expected papers,
  written before the runs. A relevant chunk can be missed and an irrelevant one can match.
* **Verified quote is not a supported claim.** The validator checks that quoted words exist in the cited chunk. It does not check
  that the claim built on the quote is true or well supported. Nothing in this report is a hallucination rate.
* **Non-deterministic small model.** A 9.7B-parameter, 4-bit local model can answer differently on the same question; one run per
  question cannot show that variance (the optional repeat shows a little of it).
* **One model, one machine.** Live numbers (quality, reliability, waiting times) are valid only for the model and settings in the
  table above, on this hardware. They say nothing about other models and nothing about clinical validity.
* **Automated results test the pipeline, not a model.** The scripted mock model always answers in the right format.
* **No clinical validity.** This is an educational prototype with synthetic patients. It does not diagnose, prescribe or choose
  treatments, and no result here supports any clinical use.
* **Failures are results.** Failed runs (502, timeouts, busy model) are counted in every share that says so and are listed in part B.
  No run was dropped and nothing was retried beyond the pipeline's documented single repair attempt.

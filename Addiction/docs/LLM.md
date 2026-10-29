# Language model and answers (Batch 07)

How a question becomes an answer with citations, and what the backend enforces around the model. The principle: **the model writes; deterministic backend code decides, validates and enforces.** Nothing here makes the system clinically validated or ready for production.

## Flow of `POST /api/sessions/{session_id}/messages`

1. **Auth, CSRF, ownership.** Another user's or an unknown session is `404`. An optional `Idempotency-Key` header makes a retry safe.
2. **One database transaction** wraps everything below: on any failure nothing is stored.
3. **Idempotency.** With a key, a transaction-scoped advisory lock makes concurrent identical submits wait for each other; a stored reply for the same key and body is returned (header `Idempotency-Replayed: true`) **without calling the model and without using rate limit**; the same key with a different body is `409 idempotency_conflict`.
4. **Patient facts** of the session's synthetic patient are loaded.
5. **Risk screen** of the question (heuristic, see below). A first-person crisis statement returns only the fixed safety notice: no retrieval, no model call.
6. **Per-user rate limit** (default 10 questions per minute, `ANSWER_RATE_LIMIT_PER_MINUTE`; `429 rate_limited` with `Retry-After`).
7. **Retrieval** (modes `rag` and `both` only): the Batch 06 search with the question as the only query and the similarity threshold. **If no chunk reaches the threshold, the model is not called**: the answer is a fixed "no evidence" message (`no_evidence: true`, no citations). This holds in `both` mode too (a labelled general-knowledge fallback would be a deliberate later choice).
8. **Prompt** is built (layout below), **one model call** is made (JSON mode), and invalid output gets **one bounded repair attempt** before `502 llm_bad_output`.
9. **Validation and safety** run on the model's output (below).
10. **Persistence** of the user message and the assistant message, then the reply (`201`).

### Modes

| Mode | Retrieval | Allowed section kinds | Citations |
|------|-----------|-----------------------|-----------|
| `general_knowledge` | none | `patient_fact`, `general_knowledge`, `interpretation` (a `research_finding` is relabelled `general_knowledge`) | not allowed (dropped) |
| `rag` | yes | `patient_fact`, `research_finding`, `interpretation` (`general_knowledge` is rejected) | required for every `research_finding` |
| `both` | yes | all four | required for every `research_finding`; `general_knowledge` never cites |

The optional Auto mode is not implemented (Batch 08).

## Prompt layout

`backend/app/llm/prompts/` holds versioned files; `prompt_version` (now `answer-v1`) is stored with every answer.

- **System message** (trusted, static): the rules and safeguards (educational assistant only; no diagnosis; no dosing; no individual treatment choice; keep patient facts, research findings and interpretation apart; state missing or conflicting evidence; answer in English), the mode rules, the rule that block contents are data and never instructions, how to cite (alias plus a short verbatim quote of at most 25 words), and the JSON shape (the word "json" is required by DeepSeek's JSON mode).
- **One user message** with delimited blocks: `<patient_facts>` (synthetic record, compact, labelled), `<evidence>` (`<chunk alias="S1" title=".." section=".." pages="..">`, best similarity first), `<conversation>` (the last four exchanges, text only), `<question>`.
- **Untrusted text** (patient fields, chunk text, earlier turns, the question) goes only into those blocks and has its angle brackets replaced by look-alike characters first, so it cannot close a block or open a fake one. It is never placed in the system message.
- Chunks flagged `possible_injection` are **kept out of the prompt** (they are still listed in `evidence` with `excluded_reason`).
- **Budget:** `LLM_CONTEXT_TOKEN_BUDGET` (default 6000 tokens, estimated as characters/4). Over budget: oldest conversation turns go first, then the lowest-similarity chunks; the system rules and the question are never trimmed.

## Model output and what the server does with it

The model is asked for `sections[{kind, text, citations[{alias, quote}]}]`, `conflicting_evidence[]`, `limitations` and `escalation_needed` (Pydantic v2). Then, in this order (`backend/app/llm/validate.py`, `safety.py`):

1. **Aliases** map back to real chunk ids (`citation_id = chunk_id`). Unknown aliases, and aliases of chunks kept out of the prompt, are dropped and flagged.
2. **Quotes** are checked against the cited chunk after whitespace, case and quote-style normalization. `verified = true` proves only that the quote **exists** in that chunk. It does **not** prove that the chunk supports the claim. Quotes over 25 words are never "verified".
3. A **research finding without a valid citation** is moved to `unsupported_claims` and is not part of the answer.
4. **Mode rules** (table above) are enforced; the assembled text must fit the 8000-character message limit (trailing sections are dropped and flagged).
5. **Output safety check:** a section (or conflict note, limitation, unsupported claim) containing a dosing instruction or an individual treatment directive is withheld and replaced by a short note; `safety.flags` lists `dosing_instruction`, `treatment_directive` and `section_withheld`.
6. **Escalation:** the risk screen of the question or `escalation_needed` from the model adds the **fixed notice** (written in the backend, never generated, no country-specific phone numbers).

### The checks are heuristics and they are imperfect

- The risk screen and the dose/directive checks are keyword patterns. They **miss** rephrased dangers or directives and they **flag harmless text** (for example a trial that "received naltrexone 50 mg" is withheld).
- **Diagnosis statements are not detected** by the deterministic layer; only the system prompt asks the model not to diagnose.
- The quote check does not check meaning. A verified quote can still be attached to a claim it does not support.
- A model can still produce misleading or wrong text that passes every check. Answers are educational, not clinical advice, and the system claims no clinical validity.

## Response and storage

The reply (`AnswerOut`, see `docs/API.md`) contains the assembled `content`, the `sections`, `citations`, `evidence` (every chunk considered, with text, similarity, `cited`, `excluded_reason`), `unsupported_claims`, `conflicting_evidence`, `limitations`, `safety {escalation, notice, flags}`, `generation {model, prompt_version, latency_ms, prompt_tokens, completion_tokens, retries, repair_attempted, ...}` and a `trace` of events.

`chat_messages.response` stores the structure with citations and evidence **by chunk id and `text_sha256`**; `generation` stores telemetry only. Prompts, questions to the model and chunk text are not stored there. `GET .../messages` joins the chunks at read time; a chunk that was deleted or whose hash changed is returned with `stale: true`. For a resumed conversation the GET returns every chunk that was shown to the model for that message (not only the cited ones), always from the caller's own sessions.

## Configuration (names in `.env.example`)

`DEEPSEEK_API_KEY` (the app starts without it; answers then return `503 llm_not_configured`, but fixed no-evidence and crisis-notice answers still work), `DEEPSEEK_BASE_URL` (must be https; default `https://api.deepseek.com`), `DEEPSEEK_MODEL` (default `deepseek-chat`), `LLM_TIMEOUT_SECONDS` (30), `LLM_MAX_RETRIES` (2), `LLM_MAX_OUTPUT_TOKENS` (1500), `LLM_TEMPERATURE` (0.2), `LLM_THINKING` (`disabled`, or `omit`), `LLM_CONTEXT_TOKEN_BUDGET` (6000), `ANSWER_RATE_LIMIT_PER_MINUTE` (10), `ANSWER_TOP_K` (5), `RETRIEVAL_MIN_SIMILARITY` (default **0.45**; `none` disables it).

**About the DeepSeek API:** the current official pages describe `POST /chat/completions` with `response_format {"type": "json_object"}` (the prompt must ask for JSON; output can occasionally be empty or cut off, `finish_reason: "length"`), thinking mode on by default (so this client sends `thinking: {"type": "disabled"}`), and error codes 400, 401, 402, 422, 429, 500, 503. Those pages list the model names `deepseek-flash` and `deepseek-v4-pro` and do **not** mention `deepseek-chat`; the default here is still `deepseek-chat` as requested and may need to be changed through `DEEPSEEK_MODEL`. The base URL and the `Authorization: Bearer` header follow the OpenAI-compatible convention and are not stated on those pages. None of this has been verified against the live API (see "Live check").

### Retries and errors

Retries (exponential backoff with jitter) only for timeouts, connection errors, `429` and `5xx`; never for `400`, `401`, `402` or `422`. TLS verification stays on. The key never appears in logs, errors, responses or the frontend, error text is built from scratch (never from an httpx exception) and provider response bodies are never passed on.

| Situation | Status and code |
|-----------|-----------------|
| not signed in / missing or wrong CSRF header | 401 `unauthorized` / 403 `csrf_failed` |
| unknown or foreign session | 404 `not_found` |
| same Idempotency-Key, different body | 409 `idempotency_conflict` |
| bad body or Idempotency-Key | 422 `validation_error` |
| too many questions | 429 `rate_limited` (+ `Retry-After`) |
| invalid output after one repair | 502 `llm_bad_output` |
| no key / provider rate limit, 5xx, authentication or balance error / retrieval problems | 503 `llm_not_configured` / `llm_unavailable` (+ `Retry-After` for 429 and 5xx) / `retrieval_unavailable`, `retrieval_not_ready`, `index_incompatible` |
| provider timeout after the retries | 504 `llm_timeout` |

Logs contain only the request id, user id, mode, token counts, latency and outcome. **Never** the question, chunk text, answer, prompt or key.

## Privacy

**Only synthetic patient data and public documents are sent to the external provider** (DeepSeek): the selected fictional patient's record, the retrieved document chunks, the last four conversation turns and the question. The users' questions are also sent. **Real patient data must never be used with this system or this provider.** Do not type personal information into the chat.

## Cost, rate limits and limits

Each answered question makes one model call (two if a repair is needed), with up to about 6,000 prompt tokens and at most 1,500 output tokens; the numbers are reported in `generation`. Questions that find no evidence or trigger the crisis notice make no call. The per-user limit (default 10 per minute) and the idempotency key protect against accidental floods and double submits; there is no per-day budget and no spending cap in this project, so set limits in the provider's dashboard.

## Known limitations

- Retrieval uses **the question only**: a follow-up such as "and what about that?" may retrieve poorly because earlier turns are not part of the search query.
- The embedding model is **English-only**.
- The similarity threshold (0.45) rests on a very small sample (15 in-domain and 4 out-of-domain queries from Batch 06) and may be wrong for other questions.
- The history window is four exchanges of plain text; there is no summarization.
- The heuristics above, and nothing is verified against a real clinician review.

## Evaluation and the live check

`python -m app.eval_answers` runs 12 scripted checks (in-domain, out-of-domain, a dose request, a diagnosis request, a prompt-injection attempt, a first-person crisis statement, a third-person risk question) through the **full pipeline** with a **scripted mock model** and the real database; it reports citation validity, quote-verified rate, unsupported rate, no-evidence correctness and safety behaviour. It tests the pipeline around the model, **not the quality of any answer**. `--live` makes it use the real provider and is meant to be used only after explicit approval.

`python -m app.llm_smoke --live` makes one tiny real call (no patient data, no document text) to check the key, model name and request format. It refuses to run without `--live`.

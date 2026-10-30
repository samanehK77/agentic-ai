# Classroom demo script (about 30 minutes)

An **educational prototype with synthetic patients**. Say so at the start: it does not diagnose, prescribe or choose
treatments, it is not production-ready and it has no clinical validation. Gmail/e-mail reporting from the original spec was
deliberately **not implemented**; there is nothing to show for it and nothing is sent.

## How to read this script (what is verified and what is not)

| Label | Meaning |
|-------|---------|
| **Verified 2026-10-30** | Observed in a real run with the local model `qwen3.5-16k` (9.7B, Q4_K_M, 16384 context) on the development machine, through the application's own code (evaluation harness or recording script), **not through the browser page**. |
| **Expected, not observed** | What the page should show from the code and the earlier synthetic-data browser checks; it was **not** seen with a real Google login and a real question in a browser. Check it in the pre-demo run. |

All waiting times and rates below were measured on one machine with one small model. They are **not promises**: quote them as
"what we saw", never as "what it does".

## Numbers to have in mind (live evaluation, 42 runs, 2026-10-30; `docs/EVALUATION_REPORT.md`)

* Of the 32 runs that reached the model, **29 answered and 3 failed** with `llm_bad_output` (502): about **91 % success, 9 %
  failures**, each failure after **115-171 s** of waiting. Expect roughly one failure in ten questions.
* Median waiting time of an answered run: **General Knowledge 35 s, RAG 76 s, Both 62 s**; the slowest answer took 98 s. A
  patient-history question took 31-37 s in every mode. Out-of-domain and dose requests that are stopped before the model take
  about 0.0 s.
* In RAG mode **63 % of the quotes the model cited were found in the cited chunk** (41 citations); the rest are shown as
  unverified. A verified quote is not a supported claim. The model cited about 8 passages for the NIDA principles question and
  only 2 of them verified: a good example for the discussion.
* The very first call after Ollama starts loads the model. This was **not measured** (the model was already loaded in every run);
  plan for a longer first wait, which is why there is a warm-up step.

## Pre-demo checklist (30 minutes before)

- [ ] Docker Desktop is running; `docker compose up -d`; `docker compose ps` shows `db` healthy.
- [ ] `alembic upgrade head` was run (from `backend/`); the 10 patients are seeded.
- [ ] The five PDFs are ingested and the **index is embedded**: `python -m app.diagnostics` shows `corpus` and `index` OK.
- [ ] **Ollama is running** and `ollama list` shows the model; `python -m app.diagnostics` shows `llm` and `llm_model_facts` OK and no
      context warning.
- [ ] API (`http://localhost:8001/api/health` returns ok) and frontend (`http://localhost:8000`) are running. Use **localhost**,
      never 127.0.0.1.
- [ ] Your Google account is a **test user** of the OAuth client; your e-mail is in `ADMIN_EMAILS` if you want the admin page.
- [ ] Browser: one window, zoom 125 %, notifications off. Keep `docs/demo/recorded_run.json` open in an editor as the fallback.
- [ ] **Warm-up** (5 minutes before the audience arrives): sign in, select P-001, ask a throw-away question in General Knowledge
      mode (for example "What is the stages of change model?") and wait for the answer. Then ask the history question below once.
      This loads the model into memory and shows the page works. Start a **new conversation** afterwards so the throw-away turn
      is not in the demo.
- [ ] Run `python -m app.diagnostics` once more: all OK.

## The demonstration

Patient **P-001** is a fictional alcohol-use case. The demo question is about opioid medication on purpose in steps 3-4: it
shows both what the documents say and what the model notices about the patient. If you prefer a matching question, use the
alcohol question in "Backup questions".

| # | Time | Step | What to do | What to say | Waiting / result |
|---|------|------|------------|-------------|------------------|
| 1 | 0-3 | Sign in | Open `http://localhost:8000`. Click "Sign in with Google" and pick the test account. | "Sign-in is Google OpenID Connect; the server keeps its own session cookie. Students only see their own conversations." | *Expected, not observed with a real login.* The header shows "Signed in as ...". |
| 2 | 3-6 | Patient | Select **P-001**. Open the patient detail. | "All ten patients are fictional. Facts about the patient are always shown separately from research and from model text." | *Expected.* Profile, history and risk factors appear. |
| 3 | 6-12 | RAG question | Mode **RAG**. Ask: **"Which medications are used to treat opioid addiction?"** | "RAG answers only from the retrieved documents; every claim must carry a citation." | **Verified 2026-10-30** (recording, `wall 49 s`; evaluation run 76 s): 4 research findings, **4 of 4 citations verified**, 5 chunks retrieved, evidence level adequate. The browser rendering is *expected, not observed*. |
| 4 | 12-16 | Evidence Inspector | Click a citation badge in the answer. | "The excerpt is the real passage; the quote the model gave is highlighted. If the model's quote were not in the chunk, the badge would say unverified." | *Expected, not observed* in a real session (checked earlier with synthetic data). |
| 5 | 16-20 | Compare with General Knowledge | New message, mode **General Knowledge**, same question. | "No documents are searched, so there can be no citations. The answer is labelled 'general knowledge (not from the documents)'." | **Verified 2026-10-30** (recording `wall 30 s`; evaluation 32 s): 0 citations, 0 evidence, and the model **noted that the patient record is about alcohol, not opioids** (a good discussion point). |
| 6 | 20-23 | Mode Both | Same question, mode **Both**. | "Document findings and general knowledge are kept in separate sections; only findings can be cited." | **Verified 2026-10-30** (evaluation, 67.5 s): 4 citations, 4 verified. |
| 7 | 23-26 | Unanswerable questions | Ask (RAG): **"How do I cook spaghetti carbonara with eggs and pancetta?"** Then ask: **"What dose of naltrexone should he take?"** | "The first has no evidence above the similarity threshold: the system says so and does **not call the model**. The second is a dosing request: it is stopped before the model." | **Verified 2026-10-30** (evaluation): no evidence in **0.04 s**, no model call; dose request **unsupported in 0.02 s**, no model call. |
| 8 | 26-29 | Activity Timeline and audit trace | Open the Activity timeline; expand the newest question. Optionally open the Admin page. | "Every question gets one correlation id. The audit log records steps, times, retrieval details and the model request, but never the question or the document text." | **Verified 2026-10-30** (recording): 15 audit events under one correlation id: `question_submitted`, 10 steps, `retrieval_executed` (5 chunk ids, 8.0 s), `llm_request` (41.0 s), `citation_validated` (4 of 4), `answer_returned` (49.0 s). The browser rendering with real data is *expected, not observed*. |
| 9 | 29-30 | Close | "What we did not build: e-mail summaries." | "Results describe one small model; read the evaluation report and its limits before quoting numbers." | |

### Backup questions (verified 2026-10-30 in evaluation runs, RAG mode)

| Question | Result seen |
|----------|-------------|
| "What does WHO recommend for managing alcohol withdrawal?" | 88.9 s, 5 citations, 5 verified, 1 unsupported claim reported |
| "Which medications are used to treat alcohol use disorder?" (earlier real run, 2026-10-30) | 73 s, 5 chunks, 3 of 5 quotes verified |
| "Does combining a medication with psychosocial treatment improve outcomes in alcohol use disorder?" | 51.9 s, 3 citations, 2 verified |
| "When did he first attend treatment, and what interventions has he received so far?" (history; answered from the patient facts, no search) | 37 s in RAG mode, 0 citations |

Avoid for a live demo: the comparison question ("How does the evidence on psychosocial interventions apply to this patient?") in
**Both** mode **failed** (`llm_bad_output`, 171 s) in the evaluation; and "What are his main triggers and risk factors according to
the case?" is routed to document search in RAG and Both mode and ends as "no evidence" (a classifier limit; use it as a
discussion example, not as a demo).

## What can go wrong and what to do

| Problem | Cause | What to do |
|---------|-------|------------|
| The answer takes more than 2 minutes | slow first call after Ollama starts, or a long answer | Keep talking about the timeline and the audit design. The browser waits up to 540 s. If it passes 3 minutes, switch to the recording. |
| "The language model returned an answer that could not be used" (502) | the small model produced invalid JSON twice (3 of 32 model runs in the evaluation, 115-171 s each) | Say it plainly: "this is a real failure mode of small models, and the system stores nothing". Ask the same question again once, or switch to the recording. |
| "The model is busy" (503 with a retry hint) | a local model serves one question at a time (another question is still running) | Wait the number of seconds shown, then ask again. |
| "No evidence" for a good question | similarity below the threshold, or a history question routed to search | Rephrase with the topic words of the document. Explain the threshold. |
| Sign-in loops or fails | `127.0.0.1` used somewhere, or the account is not a test user | Use `http://localhost:8000`; add the account as a test user; fall back to `?source=mock` (invented data, labelled DEMO) and the recording. |
| The page shows an error banner for patients | API not running or database down | `.\scripts\dev.ps1 diagnose`, restart the API (no `--reload`), `docker compose up -d`. |
| Everything is slow or the model is gone | Ollama stopped or the machine is under load | Restart Ollama, run the warm-up again, or use the recording. |
| The answer contradicts the patient or the documents | small-model limits; a verified quote is not a supported claim | Use it as the teaching moment: open the evidence and check the claim yourself. |

## Recorded-run fallback

`docs/demo/recorded_run.json` is a **recording of two real runs** (RAG and General Knowledge, the demo question) made on
2026-10-30 with the local model, **not a live demo and not screenshots**: it was produced through the application's own service
code, not through the browser page. It holds the answer sections, the short verified quotes, the evidence list (ids, titles,
pages, similarities; **no chunk text**), the workflow trace and the 15 audit events of each run. If the model is slow or fails,
say "this is a recording" and walk through it: the answer sections and their citations (RAG), the absence of citations
(General Knowledge), the trace times and the audit events under one correlation id. Nothing in the recording is invented; what the
browser would have shown is described as *expected*, not recorded.

## After the demo

Show `docs/EVALUATION_REPORT.md` (mode comparison, failures, limits) and the empty manual-observations table; ask the class to rate
three answers for faithfulness and helpfulness. Discussion questions: `docs/TEACHING_GUIDE.md`.

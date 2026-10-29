# Document ingestion (Batch 05)

How the research PDFs become cleaned, chunked text in PostgreSQL. There are **no embeddings, no LLM and no vector column** yet (Batches 06 and 07). Ingestion is a **command-line job**, not an HTTP endpoint.

The PDFs are copyrighted: they live only in `data/papers/` (git-ignored). Never commit them. Nothing in the reports, run records or logs contains document text.

## What it does

1. Reads the documents listed in `backend/db/seed_data/papers.json` (each entry has a bare `file_name`). Any other PDF in `data/papers/` is only reported as *unregistered* and never ingested.
2. Extracts text blocks with PyMuPDF (text layer only; **no OCR**), removes running headers/footers and dot-leader table-of-contents lines, normalizes the text, finds sections, and splits the text into chunks.
3. Stores the document state in the `papers` table and the chunks in `paper_chunks`. Statistics about each run go to `ingestion_runs`.

Nothing touches the network during extraction.

## Run it (Windows PowerShell)

Prerequisites: database running and migrated (`alembic upgrade head`), `python -m db.seed` done, virtual environment active, from `Addiction\backend`.

One-time setup of the token counter (about 0.5 MB, the model's tokenizer file only, no model weights):

```powershell
pip install -r requirements.txt
New-Item -ItemType Directory -Force models\all-MiniLM-L6-v2 | Out-Null
curl.exe -L -o models\all-MiniLM-L6-v2\tokenizer.json "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/tokenizer.json"
(Get-FileHash models\all-MiniLM-L6-v2\tokenizer.json -Algorithm SHA256).Hash
```

The hash printed for the pinned revision should be `BE50C3628F2BF5BB5E3A7F17B1F74611B2561A3A27EEAB05E5AA30F411572037`. The `models\` folder is git-ignored.

Then:

```powershell
python -m app.ingestion --dry-run     # read and chunk everything, write nothing to the database
python -m app.ingestion               # ingest all registered documents
python -m app.ingestion               # again: every document should say "unchanged"
python -m app.ingestion --paper who-mhgap-guideline-2023 --force
```

| Option | Meaning |
|--------|---------|
| `--dry-run` | no database writes (it may read the database to tell you what would be unchanged) |
| `--paper ID` | only this registered document |
| `--force` | re-ingest even if the file and settings did not change |
| `--chunk-target/--chunk-max/--chunk-overlap N` | override the token settings |
| `--allow-over-limit` | accept a maximum above 256 tokens (see below; not recommended) |
| `--report-dir PATH` | where the quality report goes (default `data/ingestion_reports/`, git-ignored) |
| `--show-sample` | print a 60-character sample per document |

Exit codes: `0` all good, `1` a document failed or needs OCR, `2` invalid configuration, `3` another ingestion is already running.

## Configuration

Environment variables (names are in `.env.example`) or the flags above. Invalid values stop the run with exit code 2.

| Variable | Default | Meaning |
|----------|---------|---------|
| `CHUNK_TARGET_TOKENS` | 220 | pack paragraphs up to about this many tokens |
| `CHUNK_MAX_TOKENS` | 250 | hard limit per chunk (a warning or error above 256) |
| `CHUNK_OVERLAP_TOKENS` | 40 | trailing whole sentences repeated at the start of the next chunk (must be below the target) |
| `LOW_TEXT_MIN_CHARS` | 50 | a page with fewer non-space characters is "low text" and skipped |
| `NEEDS_OCR_RATIO` | 0.30 | more low-text pages than this share: the document is `needs_ocr` and stores no chunks |
| `HEADER_FOOTER_RATIO` | 0.30 | a margin line repeating on this share of pages is a running header/footer |
| `MAX_PDF_MB` / `MAX_PDF_PAGES` | 50 / 500 | safety limits |
| `PAPERS_DIR` / `TOKENIZER_PATH` | `data/papers` / `backend/models/...` | locations |

The setting that is stored per document is `chunking_version`, for example `p1|tok=sentence-transformers/all-MiniLM-L6-v2@1110a243|target=220|max=250|overlap=40|lowchars=50|ocr=0.3|hf=0.3`. If the file hash **or** this string changes, the document is re-chunked; otherwise it is reported as `unchanged` and nothing is written. `p1` is the pipeline version and is bumped when the extraction or chunking logic changes.

## Why chunks are about 220 tokens (not 400-700)

`docs/SPEC.md` originally said "400-700 tokens". The chosen embedding model, `sentence-transformers/all-MiniLM-L6-v2`, **cuts its input off at 256 word pieces**. A 500-token chunk would silently lose more than half of its text in Batch 06. So chunks are counted with the model's own tokenizer (including the two special tokens) and kept at a target of 220 and a maximum of 250, with 40 tokens of overlap. SPEC.md was updated to say so.

## Chunking rules

- Whole paragraphs are packed until the target is reached; an oversized paragraph is split at sentence boundaries; a single sentence longer than the maximum is the only thing ever cut mid-sentence (at word boundaries).
- A chunk never spans two sections or two section types. The overlap is made of whole trailing sentences, and never a whole chunk.
- Each chunk records `page_start` and `page_end` (overlap included), a `section_title` (never invented: `NULL` when unknown) and a `section_type`.
- Chunk ids are `<paper_id>-c<ordinal:04d>`; ids and `text_sha256` are identical on every run over the same input.
- Replacing a document happens in **one transaction**: no stale or partial chunks. Documents that end up `failed` or `needs_ocr` have their old chunks removed.
- Only one ingestion can run at a time (PostgreSQL advisory lock).

## The quality report

Each run writes `data/ingestion_reports/ingestion-<UTC time>.json` (statistics only). Per document:

| Field | Meaning |
|-------|---------|
| `status` | `ingested`, `needs_ocr` or `failed` (`reason` explains the last two) |
| `action` | `written`, `unchanged` or `dry-run` |
| `pages`, `low_text_pages`, `low_text_page_numbers` | page count and skipped pages |
| `characters` | non-space characters kept after cleaning (null for unchanged documents) |
| `headers_footers_removed`, `toc_leader_lines_removed` | blocks/lines dropped by the cleaning rules (null for unchanged) |
| `chunks`, `tokens` {min, median, max} | chunk count and token statistics |
| `section_types` | chunks per `body`, `table_or_figure`, `references`, `front_matter` |
| `possible_injection` | chunks with instruction-like phrases, for admin review |

What to look at: a large number of very small chunks (low median) points to many tiny sections, tables or flowcharts; many removed headers can be good (running heads) or a sign that real text was caught; `low_text_page_numbers` should be blank or title pages; a `needs_ocr` document cannot be used until it has a text layer.

Administrators can also read the stored result through `GET /api/admin/papers` and `/api/admin/papers/{id}/chunks` (see `docs/API.md`).

## Known limitations (all of this is heuristic)

- **Reading order.** Two-column pages are detected by block positions; tables, sidebars and flowcharts (the mhGAP Intervention Guide is full of them) can come out in a surprising order or as many small fragments.
- **Headers and footers** are found by repetition in the page margins. Headers that change per chapter, or that are split into different blocks on some pages, can survive as short chunks; rarely, a repeated margin line that is real content could be removed.
- **Section titles** come from the PDF outline (by page, so a title can be one page late) or from font-size/bold heuristics, which also pick up labels such as "CLINICAL TIP" or table headers. Titles can be noisy; they are never made up.
- **Section types** are guesses: *front matter* is the pages up to the table of contents (or the first page), *references* start at a heading such as "References" and run until an appendix-like heading or the end, *table_or_figure* is detected from captions, many very short lines or mostly digits. A reference list in the middle of a document or a table that looks like prose will be mislabelled.
- **Hyphen joining** happens only when the next fragment starts in lowercase, so some real line-break hyphenations stay split.
- **Injection marker.** `possible_injection` matches a short list of phrases ("ignore previous instructions", "system prompt", ...). It has false positives and false negatives. It is a marker for review, **not a security control**: retrieved text is untrusted data in every later batch regardless of the flag.
- **No OCR.** Scanned pages are skipped; a document with too many of them is `needs_ocr`.
- This batch does not measure retrieval quality. That is Batch 06.

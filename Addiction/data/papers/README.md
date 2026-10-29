# Research corpus

The five research documents used by MindEvidence Lab. PDF files are not committed
to the repository (see `.gitignore`); they live only in this folder on each machine.
Only the documents registered in `backend/db/seed_data/papers.json` are ever ingested;
any other PDF placed here is reported as "unregistered" and ignored.

| # | Document | File |
|---|----------|------|
| 1 | WHO mhGAP Guideline for mental, neurological and substance use disorders (2023) | `who-mhgap-guideline-2023.pdf` |
| 2 | NIDA, Principles of Drug Addiction Treatment: A Research-Based Guide (Third Edition) | `Principles of Drug Addiction Treatment A Research Based Guide.pdf` |
| 3 | WHO mhGAP Intervention Guide, Version 2.0 | `who-mhgap-intervention-guide-v2.pdf` |
| 4 | Psychosocial Interventions for Alcohol Use Disorder: A Review of Efficacy, Mechanisms, and Clinical Implications | `Psychosocial Interventions for Alcohol Use Disorder A Review of Efficacy Mechanisms and Clinical Implications.pdf` |
| 5 | Cochrane review: Combined pharmacological and psychosocial interventions for alcohol use disorder (2025, Issue 3, CD015673.pub2) | `Combined pharmacological and psychosocial interventions for alcohol use disorder (Review).pdf` |

## Notes
- Document 5 is the Cochrane review named in `docs/SPEC.md`; document 4 is an additional review.
- Files 1 and 3 were downloaded from WHO IRIS; files 2, 4 and 5 were added manually.
- Metadata (publisher, year, DOI) was read from the first pages of each document; `metadata_source` in the database says where each value came from.
- How the documents are ingested: `docs/INGESTION.md`.

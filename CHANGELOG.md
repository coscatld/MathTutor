# Changelog

## 0.4.2 — RAG integration

- Share retrieval orchestration across product paths; retain conversation/owner scope, source ranges and persistent citation receipts. Deletion removes receipts; disabling a source blocks new retrieval while preserving authorized historical receipt reads.
- Ship local parsing, chunking, lexical retrieval and traceable citations. Keep optional embeddings and rich PDF parsing separate from the distributable baseline; scanned PDFs do not gain OCR support by implication.
- Preserve incomplete response bodies and uncertain continuation seams. Recognize a closed numeric root list and a split parenthesized decimal without inserting a notice inside the literal; a provider `stop` alone never proves a seam safe or a mathematical assertion true.
- Add migration 023 for citation receipts and retain supported backup/restore and shutdown ownership boundaries.
- Publish sanitized response-only regression fixtures with synthetic replay inputs; keep original request logs, budgets, credentials and user databases local. Evaluation corpora are test fixtures, never automatically imported teaching resources.

Quality evidence remains provisional: historical semantic failures, BUDGET_BLOCKED real retesting and INSUFFICIENT_EVIDENCE formal acceptance are not changed by integration. See [release notes](docs/RELEASE_0.4.2.md).

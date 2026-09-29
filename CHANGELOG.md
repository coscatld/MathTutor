# Changelog

## 0.4.3 — Calm workspace UI

- Restyle the student workspace for primary and secondary school learners: a single cool-blue accent on a white canvas, hairline borders and generous whitespace, with colour reserved for actions and the current location.
- Replace roughly 470 hard-coded colour utilities across 30 components with semantic theme tokens. `--primary` (fill, always white text) and `--primary-text` (text/icons) are split because no single blue passes 4.5:1 both under white text and on the dark canvas.
- Use a system sans-serif stack for Chinese and Latin text; no network fonts. The serif token now resolves to the same stack.
- Empty conversations centre the greeting and composer together; the first message returns the composer to the bottom. The knowledge-scope entry moves to a header icon, and the scope notice now appears in the empty state.
- Redesign the sidebar (tinted background, soft new-chat button, highlighted current item, hover-revealed delete), the composer (24px radius, round send button), student bubbles and toasts.
- No change to teaching policy, retrieval, verification, persistence or the database (migration head remains 023).

## 0.4.2 — RAG integration

- Share retrieval orchestration across product paths; retain conversation/owner scope, source ranges and persistent citation receipts. Deletion removes receipts; disabling a source blocks new retrieval while preserving authorized historical receipt reads.
- Ship local parsing, chunking, lexical retrieval and traceable citations. Keep optional embeddings and rich PDF parsing separate from the distributable baseline; scanned PDFs do not gain OCR support by implication.
- Preserve incomplete response bodies and uncertain continuation seams. Recognize a closed numeric root list and a split parenthesized decimal without inserting a notice inside the literal; a provider `stop` alone never proves a seam safe or a mathematical assertion true.
- Add migration 023 for citation receipts and retain supported backup/restore and shutdown ownership boundaries.
- Publish sanitized response-only regression fixtures with synthetic replay inputs; keep original request logs, budgets, credentials and user databases local. Evaluation corpora are test fixtures, never automatically imported teaching resources.

Quality evidence remains provisional: historical semantic failures, BUDGET_BLOCKED real retesting and INSUFFICIENT_EVIDENCE formal acceptance are not changed by integration. See [release notes](docs/RELEASE_0.4.2.md).

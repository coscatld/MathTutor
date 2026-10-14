# Changelog

## Unreleased

### Student model
- The uncalibrated legacy 0-1 mastery estimate no longer reaches practice generation: it is removed from the model prompt, and the template statement uses verified error counts from recent attempts instead.
- Every verified error class the verifier reports now steers the next practice item and the teaching guidance: sign errors, missing roots, extraneous roots, equality-preservation errors and computation errors each map to a skill in the skill graph for the matching problem family. Previously only two classes did.

### Persistent turn traces and failure replay
- Migration 024 adds `turn_traces`: one structured row per tutor turn (command, actions, status, finish reason, error code, latency, tokens, model, formula-check counts, template fallback). No student or tutor text is copied; the row is deleted together with its conversation.
- `GET /desktop/diagnostics/turns` returns persisted health (failure, partial, provider-error and refuted-formula rates, latency p50/p95, tokens) with threshold alerts once at least 20 turns exist, plus the recent turns. These survive restarts, unlike `loop_health()`.
- `scripts/replay_turn.py` replays a recorded conversation up to a chosen turn in a throwaway database, reading the original read-only, and reports whether state, actions and errors reproduce.

### Fixed multi-turn evaluation
- 14 fixed multi-turn scenarios are played through the real app and scored automatically on the six tutor-v2 dimensions (math, relevance, evidence, actionability, adaptation, coherence). Scoring uses rules and the local verifier only; there is no human rater.
- `scripts/tutor_multiturn_eval.py` writes JSON and Markdown reports and exits non-zero when the release gate fails. `--mode live` evaluates a real model before it goes to production.
- Formula extraction no longer treats quoted student answers, brace exponents in plain text or `\text{或}` root lists as tutor claims.

### Explanations: formulas go through verify_math
- Model-written explanations (free chat, knowledge mode and the model writer on the teaching path) are scanned for formulas. Each arithmetic equality, claimed identity and derivation step is checked by the same `verify_math` core as the knowledge tool. Derivation steps are compared with the bound problem when there is one, otherwise with the first equation of the explanation.
- On the teaching path, a refuted formula never reaches the student: the verified template text is delivered instead.
- In free chat and knowledge mode, each refuted formula is marked in place with the reason, and the notice above the text says how many formulas failed.
- When every formula passes, the notice says how many were checked and that the prose is still unverified. When some formulas cannot be checked automatically, the original "未经逐句数学核验" notice stays, with the counts added.
- Free chat and knowledge mode get one correction round: when a formula is refuted, the model is told which formulas failed and why and answers again; the corrected text is kept only if fewer formulas fail, and anything still wrong is marked in place. The turn gets exactly one extra model step for this, and a failed correction call leaves the first answer and turn status unchanged. Turn traces record whether a correction was attempted and succeeded.
- The knowledge tool `verify_math` now uses the shared core and reports an unparseable expression as a tool error.

## 0.5.0 — Hint before the answer, diagnosed misconceptions, function graphs

Teaching policy changes; the database is unchanged (migration head remains 023). Upgrading from 0.4.5 needs no data migration.

### Teaching
- An open problem now needs one hint before its full solution. The request is refused with `HINT_REQUIRED` without changing problem state, and the "看答案" button is disabled with the reason. Solved problems and already-shown solutions stay reviewable. This supersedes tutor-v2 item C02 ("zero-hint solution allowed").
- A message that both submits an answer and asks for the solution keeps its assessed attempt when replayed after the refusal.

### Learning profile and export
- "活跃错误概念" counts diagnosed rules from assessed wrong or partial attempts instead of a fixed 0. An independent correct attempt on the same skill resolves them; assisted success does not.
- The data export lists the same misconceptions (rule, label, skills, last seen). No model confidence is claimed.

### Function graphs
- Ask "画出 y = x^2 - 2x - 3 的图像" or press "看图像" under a linear, quadratic, simplification, system or inequality problem.
- The server parses a whitelist grammar (no `eval`), samples points and marks zeros, vertex, intercepts and intersections; the client draws them on a canvas, with hover read-out, legend and dark-mode colors. The model never supplies coordinates, and only server-owned `SHOW_GRAPH` messages render as graphs.
- While a problem is open, answer points stay unmarked and a graph of that problem counts as help, so a later answer is recorded as assisted.
- Model context receives a one-line placeholder instead of graph point data.

## 0.4.5 — Page styles and visual refresh

No change to teaching policy, verification, retrieval, persistence or the database (migration head remains 023). Upgrading from 0.4.4 needs no data migration.

### Page styles
- Choose a style in Settings → Appearance or from the sidebar footer: Follow system, 纸墨 (paper), 夜读 (night), 暖纸 (warm sepia) and 星夜 (starry). Each option has a live miniature preview; switching cross-fades and takes effect immediately.
- The choice is a display preference kept in local browser storage by `web/lib/theme.ts` and applied before first paint. It lives outside `features/math-tutor/desktop`, so the "no browser storage for credentials" invariant still holds.

### Visual refresh
- New mark: a staircase of steps reaching a goal point. The startup screen draws it instead of a spinner.
- A faint graph-paper motif marks where mathematics happens: displayed equations (including a formula written alone on one line), the student's turn, starter problems and the onboarding worked example. Starter problems are typeset with the bundled KaTeX fonts; no network fonts.
- Shared card, button, input, note and choice styles across the workspace, profile, practice, documents, memory, knowledge base, every Settings section, the initial assessment, onboarding, startup, login and registration. Login and registration are now in Chinese.
- Semantic status colours (success, warning, destructive) replace fixed palette classes so every style keeps correct contrast.
- Short, eased motion for message entry, presses, hovers, popovers and dialogs; all of it respects reduced-motion settings.

## 0.4.4 — Formal release

This installer supersedes the 2026-09-30 pre-release. Migration head remains 023.

### Student tutoring path

- Put starter exercises, the current goal, hints, writing, examples and practice invitations directly in the conversation.
- Follow a positive understanding self-report with a fresh, verified check. Preserve the original problem and keep diagnostic evidence separate from independent target work.
- Use independently verified error history for concrete teaching guidance, hint depth and the structure of follow-up exercises.
- Offer an explicitly chosen, verified prerequisite exercise for unsupported questions. Preserve the original request and disclose unverified model explanations in live output and history.
- Keep unfinished formulas partial and allow bounded continuation with the saved raw context.

See [implementation and validation notes](docs/TUTOR_MAIN_PATH_2026-10-13.md).

### Trained DKT on the teaching path

- Ship the same hash-pinned ASSISTments 2009 checkpoint (seed 29). NumPy runs those weights. Torch stays excluded. A missing or damaged package still falls back without blocking grading.
- The package remains `mode = shadow` and cannot authorise itself (`controls_teaching = false` on the package).
- For product skills that map through `assist2009-mt-topic-v1`, the product reads a probability from those weights. After at least one eligible personal attempt, that probability can tighten the next hint or shift practice difficulty.
- The number is not a mastery percentage and is not shown to the student. `learning_effect_verified` stays false. Unmapped skills stay null. With no personal attempts, the prior is stored and does not change assistance or get narrated as this student's history.

### Verified problem scope

- One-step linear inequalities are solved and checked, including a direction flip when the coefficient is negative. An answer that drops the inequality and writes only the boundary equation is incorrect.
- Fully numbered word problems and a few numeric geometry sentences compile into existing arithmetic or linear problems and are checked there.
- Graphs, parameters, trigonometry, quadratic inequalities, and word problems that are missing a number stay on the recovery path.

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

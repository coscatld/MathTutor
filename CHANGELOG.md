# Changelog

## 0.7.0 Mac r2 — Distribution repair

- Replace the incomplete Electron linker signature with full ad-hoc application and bundled-runtime signatures. Fail packaging on a missing resource seal, tampered resource or invalid native signature; inspect the final readonly DMG independently. Developer ID/notarization remain required for default Gatekeeper approval.
- Prevent packaged Python imports and Next.js ISR from writing caches into the sealed application; verify the signature again after writable-copy startup and page requests.
- Document the withdrawn original Mac artifact and explicit per-app first-open trust steps. Keep the application version at 0.7.0 and the original Windows installer unchanged.
- Remove the knowledge page's community shortcut and import explanation banner; align the empty library and welcome panels.
- Make the restore concurrency test release its pause explicitly, allow the aggregate lifecycle budget, and report lifecycle stages on timeout. Preserve concurrent-request rejection, successful restore and SQLite sidecar assertions.

## 0.7.0 — Knowledge vault and creator community

- Use the formal product name “MathTutor——基于学习过程追踪与可验证解题的开源数学智能辅导系统”; keep `MathTutor` as the navigation, bundle and executable name. Publish v0.7.0 as a non-prerelease GitHub Release with verified Windows x64 EXE and macOS Apple Silicon DMG assets and SHA-256 checksums. The binaries have no publisher certificate; macOS notarization remains incomplete.
- Add open-source contribution, conduct and security guides, Issue/PR templates, importable quadratic-function question and plugin examples, and a roadmap for a GitHub resource index, plugin version management and contribution review. Keep code execution behind explicit user trust and consent.
- Unify answer-source selection in conversation materials. Manage folders, Markdown edits, versions, tags and backlinks in the knowledge vault; import and export shared question packs without widening a conversation's source scope or marking reference answers verified.
- Add direct imports of user-downloaded community files and installed-plugin management. Keep creator APIs and GitHub/custom HTTPS catalog integration in developer documentation; imported question packs become editable personal copies.
- Split document and plugin imports into separate entry points. Import UTF-8 Markdown/TXT files and folders with relative paths, preserve TXT names through edits and exports, reject wrong resource types before writes, and avoid accumulating hidden source-cache entries for shared files.
- Import downloaded plugin or resource files in one action, without editing configuration files; use simple settings and readable text result exports. The community page focuses on discovery and installed plugins. Add a runnable offline bundler and [developer guide](docs/PLUGIN_DEVELOPMENT.md) for building, testing, updating and sharing plugins.
- Install strict, declarative teaching plugins for deterministic exam building, evidence-based mistake review and learning trends. Require per-plugin data consent and explicit activation; preserve user configuration on upgrades, disable upgraded plugins, and stop subsequent calls on uninstall. Empty learning histories remain empty.
- Import explicitly trusted Python/TypeScript single files or bounded code ZIPs. Run `/command arguments` through the host once, feed actual reference results to native or non-native models, and retain bounded replay receipts. Ship runtimes, require separate code consent, and label this execution as local-account code rather than an OS sandbox.
- Connect the trusted, in-process creator SDK to the real tutor tool loop with strict schemas, bounded results and execution budgets. Explicit directory grants constrain text-file tools; grants expire on restart, and writing requires the current user's file-write request. This SDK is not an arbitrary third-party code sandbox or package installer.
- Keep plugin statistics, reference material, memory and tool receipts separate from verified solution evidence and DKT/mastery updates. SQLite backup format and migration head remain unchanged at `024`; independent community settings require their own export, and successful database restore clears plugin data consent.
- No paid model calls, new model weights or benchmark re-evaluation are included in this update. Historical scores and figures retain their original evaluation scope. See [0.7.0 release notes](docs/RELEASE_0.7.0.md) for data flow and packaging boundaries.

## 0.6.5 — Learning support, effective memory and curriculum coverage

- Redesign teaching hints, conversation resources and knowledge scope with clear loading, saved and retrieval states. Remove the duplicate top-level collapse control and preserve keyboard focus and responsive reading space.
- Deliver enabled, user-authored or confirmed memory to ordinary chat and structured model tutoring; select recent edits within a whole-record budget. Keep unconfirmed inference, other owners and deleted/disabled entries out of new context; memory never grants mastery or solution disclosure.
- Persist strictly increasing, owner-scoped memory update times so tied or backward-moving clocks cannot push a newly edited preference out of the prompt budget. Serialize SQLite timestamp selection with writes and preserve ordering across restarts.
- Cover 383 curriculum points with 801 original reference questions and worked answers, alongside 353 locally step-verifiable exercises. Add grade filtering, distinct verification labels and question-only tutor launches; fix mismatched arithmetic templates and add the requested advanced topics.
- Preserve frozen benchmark results without new paid model calls. Distribute Windows x64 and macOS Apple Silicon installers with version-specific package and startup evidence.

## 0.6.4 — Student-model-guided dialogue and response boundaries

- Read the bundled DKT and owner-scoped, same-skill independent observations before ordinary chat. Change explanation granularity only with corroborating evidence; preserve the student's current request and unknown high-school coverage.
- Keep DKT guidance in structured teaching plans alongside concrete error guidance. Require attributable target-skill history and a finite probability; global history alone cannot unlock adaptation.
- Respect current hint/full-solution and presentation requests across embedded conversations and mathematical repairs. Deliver routine verification scope separately from the answer body, including replay and restored history; refutations remain prominent.
- Check explicit rational-coefficient polynomial derivatives exactly, with bounded degree and syntax. Reject invalid or oversized tool arguments instead of silently truncating them.
- Reuse the application's database engine for health checks and dispose temporary health-check engines, so probes cannot leave SQLite connections open at shutdown.
- Provide Windows x64 and macOS Apple Silicon installers with platform-specific startup evidence; packages are unsigned and the DMG is not notarized.
- No new model weights, benchmark-score changes or paid model calls are included in this update.

## 0.6.3 — Preserve the original question and let the Tutor teach

- High-school pasted tasks enter agent-led discussion, with durable original questions, current doubts, and recent explanations.
- The model can explain motivations, ask a useful question, verify local calculations, or draw; natural follow-ups keep the saved question. Explicit verified practice retains its evidence protocol.
- Routine verification scope folds below each answer; genuine refutations stay visible. Function notation and separate branches no longer trigger false equation comparisons.
- Complete bold text and one-sided limits no longer falsely appear truncated. Images remain attached to saved original questions.
- Model reasoning and figure definitions remain fallible; no claim of whole-problem verification or measured learning benefit.

## 0.6.2 — Draw named examples and keep the drawing conversation

- Requests such as 「画一个图展示一下双曲线」 choose a clearly labelled standard example with parameter sliders, including offline. Ellipses, parabolas, inverse proportional functions, sine and cosine have the same fallback. Given equations and conditions are preserved.
- Short replies such as 「都可以」「你定」 continue the previous drawing request, including persisted conversations from before this fix. A different student topic or an already delivered graph stops this continuation.
- Offer `draw_scene` for relevant mathematical concepts and related short follow-ups, allowing the model to choose a useful figure and example parameters. Keep the scene compiler, math verification and answer disclosure rules.
- Add 28 drawing autonomy regressions and verify the real canvas redraws when a slider changes. Windows installed-startup acceptance reads the expected version from desktop package metadata.

## 0.6.1 — Recover Windows startup migrations

- Serialize migrations for each database with an OS-owned process lock, and commit SQLite schema changes and version updates in one transaction. Concurrent first launches can no longer leave both 023 and 024 in the version table.
- Recover the observed 023/024 state only after a verified backup, complete current table/column/key checks, and SQLite integrity and foreign-key checks. Unknown or incomplete databases remain unchanged.
- Keep one desktop instance and focus its window on repeated launch. Persist startup output in `logs/startup.log`; report failed child processes immediately with their stderr and log location.
- Add process-race, crash-release, rollback, encrypted/plaintext recovery, rejected-recovery, and desktop startup tests, plus installed Windows startup acceptance in Chinese paths.

## 0.6.0 — Verified explanations, interactive scenes, and the K-12 question bank

### Windows CI
- Backup scheduler tests now wait for the full backup, manifest and retention cycle instead of treating a database file or a fixed delay as completion. This removes a timing race on slower runners and checks that a wake request during an active backup schedules the next cycle.
- A WebSocket disconnect now waits for an in-flight delivery acknowledgement to finish before releasing its request. Cancelling that SQLite read before fetching could retain a cursor, block the shutdown checkpoint and prevent Windows from deleting an evaluation's temporary database.

### Question bank and learner stage
- A K-12 catalog in People's Education Press textbook order: 24 terms (一年级上册 … 九年级下册, then 人教A版 2019 必修第一册 … 选择性必修第三册 and a 高三下 review term), 149 units and 359 knowledge points.
- 68 knowledge points carry deterministic practice generated from 41 templates; each of the 449 problems is kept only when the local solver and verifier accept it as the intended family. 42 knowledge points carry 数形结合 demos that the scene reader draws.
- Settings → 学段 (小学 / 初中 / 高中, optional grade) sets which terms the bank shows by default. The 题库 page starts a new tutoring conversation with a chosen problem or demo.
- API: `GET/PUT /desktop/settings/learner`, `GET /desktop/exercise-bank`, `GET /desktop/exercise-bank/points/{code}`. The path avoids the `question` route marker, which stays forbidden.
- Fix: input whose variables cancel to a number (e.g. `3x-3x+2`) crashed the parser's arithmetic display.

### Canvas drawing skill (figures only through the canvas)
- New skill `src/mathtutor/skills/canvas_drawing/` (`SKILL.md` plus a cached loader). In free chat, on maths questions and when the student asks for a picture, a model with native tool calling is offered `draw_scene` next to `verify_math`, and the skill text joins the system message. The scene author prompt reuses the same definition format and rules.
- The application builds each `draw_scene` definition with the Scene v2 builder and returns `drawn` or `rejected` with the Chinese validation error, so the model can fix it. At most 2 scenes are accepted and 4 draw attempts made per turn, within the existing step budget.
- Accepted scenes are appended after the formula check as `mathtutor-scene` blocks and the message is sent as `TUTOR_CHAT_FIGURE` (chip 「讲解配图」). The streamed preview never shows figures. Turn traces record drawn, rejected, delivered and removed figures.
- Model-authored text in free chat, knowledge mode and the teaching writer passes through `sanitize_figures`. It removes forged scene or graph blocks, Markdown images, HTML img/svg/canvas, Mermaid/TikZ/SVG/plotting-code blocks, LaTeX picture environments and ASCII-art blocks, and puts 「（图示请用画布查看）」 in their place. Maths, Markdown tables and LaTeX are kept. If free chat removed a figure and none was drawn, the model is asked once to redraw with `draw_scene`.

### Scenes (数形结合, end to end)
- Requests such as 「演示椭圆 x^2/4+y^2/3=1 上的动点 P(2cos t, √3 sin t) 到焦点 F(1,0) 的距离」 or 「画出三角形 ABC，A(0,0)，B(4,0)，C(m,3)，三角形ABC的面积」 are now read without a model: point definitions, segments, lines, rays, vectors, polygons and distance / angle / area readouts are extracted from the sentence, a point that uses a parameter becomes a moving point with a trace and a play button, and references to undefined points are dropped.
- The view ignores unbounded boundaries (half-planes, hyperbola branches) when the scene has anything bounded; regions are filled in one pass with a crisp boundary, dashed for strict inequalities.
- The message chip for graphs reads 「图像」. A contract test feeds real backend scenes through the client validator and renderer.

### Scenes (数形结合, backend)
- New `mathtutor-scene` block (Scene v2, `docs/SCENE_SPEC.md`) on `SHOW_GRAPH` messages: implicit curves, inequality regions, parametric and polar curves, points, segments, polygons, circles, tangents, text, parameter sliders and live readouts.
- Expressions are compiled by a whitelist tokenizer and parser into the contract's JSON AST (no `eval`); every limit and reference rule is checked on the server. View ranges are sampled on the server; parameter-free scenes get intersections and axis intercepts as marks, never while a problem is open.
- Requests such as 「画出 x^2/4+y^2/3=1 和 y=kx+1」, regions, circles and `r = f(θ)` are read deterministically; other letters become sliders. A single plain `y = f(x)` still uses the function graph.
- When that fails and a model is configured, the model is asked once, on the auxiliary role, for a definition JSON. Its strings go through the same compiler, any marks it offers are dropped, and the scene is labelled 「示意图：定义来自模型，图形由应用计算，未经数学核验」. Any failure falls back to the guidance message without failing the turn.
- Model context receives `[已展示数形结合图：…]` instead of scene data.

### Encryption at rest (opt-in)
- Database encryption with SQLCipher, off by default. Turning it on or off in Settings → Advanced → Data encryption records the wish; the conversion runs at the next start, before anything opens the database: integrity check, export into a temporary file in the new mode, integrity check and identical row counts, atomic swap. Any failure leaves the original file and the marker unchanged.
- Keys live only in the OS credential store; an in-memory store is never used for real data, and without a persistent key store encryption reports itself unavailable.
- Backups are SQLCipher files keyed by a separate backup key whenever a key store exists. "Show recovery key" reveals it on request, and restore accepts it when the key store entry is gone. Restore converts into the live database's mode; older plaintext backups stay restorable.
- Two different SQLite builds never open the same live database in one process (their shared-memory locks do not see each other; this crashed under a concurrent writer during development). A plaintext database is first snapshotted with the standard library and only that standalone file is encrypted; an encrypted database is only ever opened by SQLCipher.
- Every database opener (async engine, Alembic, pre-migration backup, release probe, migration check, offline readers) goes through one module. Adds the `sqlcipher3` dependency to both packaged runtimes. Uploaded source files are still plain files. Not yet verified on a real Windows machine.

### Tutoring tool loop
- On maths questions in free chat, a model with native tool calling may call `verify_math` before answering, at most four times per turn. The application checks the arguments against a schema, runs the shared verifier and returns a receipt (verified, refuted, unchecked or rejected); the model corrects itself and the final answer is ordinary prose that still passes the formula check. Apart from `draw_scene` (canvas drawing skill) no other tool is offered; everyday chat keeps streaming without tools. Turn traces record tool calls.

### Quadratic inequalities
- New problem family `quadratic_inequality` for one-variable quadratic inequalities with rational roots; irrational boundaries are rejected rather than approximated. The solution set is a union of exact intervals and is rendered as two-sided ranges, a between range, a single point, "x ≠ a", all reals or no solution.
- The strategy reuses the quadratic-equation root steps and adds the parabola-sign step. The verifier checks the boundary roots and then compares the polynomial's sign at test points around every root with the claimed set, independently of the strategy's reasoning.
- Student answers such as `x<2或x>3`, `2<x<3`, `x≠2`, `全体实数` are read as sets and compared exactly; feedback names the specific problem (wrong interval direction, boundary inclusion, a missing part of the set). Typed solution sets now route as answers, which also helps linear inequalities.
- Teaching goals, hints, worked examples, graphs, formula anchors and practice focus cover the new family. Worked solutions of inequalities now show the problem's own variable instead of always `x`.

### Streaming in free chat
- OpenAI-compatible providers can stream (SSE). Free chat shows the answer sentence by sentence, but a sentence is released only when its math delimiters are closed and every formula so far passes `verify_math`. The first failing formula stops the preview; the full answer then goes through the check and correction round, and the final message replaces what was shown.
- The teaching path stays non-streaming: its disclosure guard needs the whole text before anything can be shown.
- Servers that ignore streaming are read as a normal response, and a server that rejects streaming with HTTP 400 is asked once without streaming.

### Cost and budget
- Settings → Tutor gains "模型费用与预算": input and output prices per million tokens, a daily money budget and a daily token budget. No vendor prices are built in; without prices `estimated_cost` stays empty and only tokens are counted.
- Each turn's cost is computed from the provider's token usage and recorded on the turn trace; diagnostics health reports total cost and how many turns were blocked by the budget.
- Once today's usage reaches the budget, model calls are blocked for the rest of the day: every model role looks unconfigured, so tutoring, chat and knowledge mode take their existing template or retrieval-only fallbacks, and the student sees one notice. Verification and learning records are unaffected.

### Student model
- The uncalibrated legacy 0-1 mastery estimate no longer reaches practice generation: it is removed from the model prompt, and the template statement uses verified error counts from recent attempts instead.
- The trained (ASSISTments) DKT may now change teaching only when the skill maps to a product skill and the student has at least one own attempt; a foreign prior alone no longer adds guidance text. Support moves by at most one level, practice difficulty by one level, and `MATHTUTOR_DKT_TEACHING=off` turns both off. Every adjustment is recorded on the turn trace and shows up as `dkt_adjust_rate` in the diagnostics health.
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

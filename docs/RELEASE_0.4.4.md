# MathTutor 0.4.4 release notes

## Scope

0.4.4 is the formal Windows release. It supersedes the 2026-09-30 pre-release installer, which loaded the same checkpoint in shadow mode and did not let it change teaching. The database schema is unchanged: migration head remains 023, so no data migration is needed from 0.4.3. Create and verify a backup, then quit the app, before replacing an older install.

The formal build includes the student tutoring path (starter exercises, in-conversation next step, verified understanding checks, error-history hints, and a disclosed recovery exercise for unsupported questions) and a wider verified problem scope. See [the tutoring-path note](TUTOR_MAIN_PATH_2026-10-13.md).

## What is bundled

- `src/mathtutor/learning/knowledge_tracing/assets/assist2009-source-v2-seed29/`
  - `model.json`: a single-layer LSTM (hidden 64) in `tutor_model_dkt_v1` format. It is trained on the public ASSISTments 2009–2010 skill builder data, with 122 source skills and a validation-fitted calibration temperature of 1.299. It is copied byte-for-byte from the frozen research delivery (SHA-256 `d30fb23c…03a4`).
  - `manifest.json`: provenance, the pinned hash, the shadow policy and a numeric self-check.
- Seed 29 was chosen as the lowest validation (selection) loss among seeds 17/29/43; the test split was not consulted. The research delivery recorded PyTorch/NumPy parity for this checkpoint as passed, with max logit error 2.4×10⁻⁷.
- NumPy is now a declared runtime dependency. Previously it was only a development extra, so the packaged runtime had no NumPy and DKT could not load at all. Torch is still excluded from the runtime.

## How the checkpoint is used

- `SourceModelPackage` verifies the following before use: byte size and SHA-256, format, vocabulary and weight dimensions, finite weights, calibration bounds, and a 16-step numeric self-check against an independent float64 reference.
- Only JSON is read. No pickle and no package-supplied code runs. NumPy performs inference. The research `.pt` file is not loaded on the product path.
- A loaded package is always `mode = shadow` and `controls_teaching = false`. The package cannot authorise itself.
- Product skills that appear in `assist2009-mt-topic-v1` (signed operations, fractions, the distributive law, linear isolation, quadratic roots, and system completeness) are queried against the matching ASSISTments skill ids. The forecast records `probability_source = assist2009_trained_dkt`. After at least one eligible independent free-response attempt, a low probability can shorten the next step and lower practice difficulty, and a high probability can ask the student to write more. The sentence shown to the student does not contain the number.
- Skills outside that map stay `probability = null`. Nothing is invented for them. With zero personal attempts, the prior is stored and does not change the assistance level.
- The probability is not a mastery percentage. `learning_effect_verified` stays false. This release does not claim that the model improves learning.
- If a package is missing or damaged, the service reports `unavailable_fallback`. Learning facts, grading and recommendations keep working.
- The learning-state summary reports `dkt_mode = shadow`, `dkt_controls_teaching = true` when the checkpoint loaded, and `dkt_teaching_scope = mapped_assist2009_skills`. The UI does not show a probability.

## Verified problems

- Existing families remain: arithmetic, polynomials, linear equations, quadratic equations, and linear systems.
- One-step linear inequalities are solved and checked. A negative coefficient flips the relation. Writing only the boundary equation is incorrect.
- Fully numbered sentences of a few fixed shapes (a number times N plus or minus M, a unit-price purchase, a triangle's third angle, a rectangle or square perimeter or area, and a perfect-triple hypotenuse) compile into those families and are checked there.
- Graphs, parameters, trigonometry, quadratic inequalities, and word problems missing a number stay on the recovery exercise. That exercise is not a solution of the original question.

## Packaging

- The package allowlist ships `learning/knowledge_tracing/assets/*/*.json`, and the audit now requires `numpy` in the relocated runtime.
- The Windows runtime was rebuilt from the official Python 3.12.10 embeddable package with `numpy` 2.5.3.

## Validation

- The 2026-09-30 pre-release recorded backend 1414 passed, 11 skipped, and a packaged-runtime self-check of the shadow loader.
- This formal build keeps that checkpoint and adds tests that the mapped forecast comes from those weights, that one eligible incorrect attempt changes the next probability, that a cold start does not narrate the prior or move difficulty, and that linear inequalities plus the numbered word and geometry sentences verify.
- On the release machine, `pytest tests` reported 1565 passed, 4 skipped, and 3 failed. Two PDF failures happen because that interpreter can import PyMuPDF and then records `image_count = 0` instead of leaving it unmeasured. The third runs isolated CPython, which cannot see the ad-hoc `fastapi` install. Frontend node tests: 179 passed. The packaged runtime does not include PyMuPDF.

Not verified: installation and uninstallation on a clean machine, macOS and Linux packages, a new live model-quality evaluation, and any measured effect on real students. The ASSISTments terms for redistributing derived weights have not been confirmed; see `THIRD_PARTY_NOTICES.md`. The Windows installer is unsigned. The exact SHA-256 is the value published with the GitHub release assets, not the pre-release hash.

# MathTutor 0.4.4 release notes

## Scope

0.4.4 bundles a trained DKT (deep knowledge tracing) model with the desktop application and loads it at startup in **shadow mode**. Teaching, hints, grading, recommendations and the learning profile are unchanged and continue to come from the evidence tracker (`policy_source = evidence_tracker_v2`). The database schema is also unchanged: migration head remains 023, so no data migration is needed from 0.4.3.

## What is bundled

- `src/mathtutor/learning/knowledge_tracing/assets/assist2009-source-v2-seed29/`
  - `model.json`: a single-layer LSTM (hidden 64) in `tutor_model_dkt_v1` format. It is trained on the public ASSISTments 2009–2010 skill builder data, with 122 source skills and a validation-fitted calibration temperature of 1.299. It is copied byte-for-byte from the frozen research delivery (SHA-256 `d30fb23c…03a4`).
  - `manifest.json`: provenance, the pinned hash, the shadow policy and a numeric self-check.
- Seed 29 was chosen as the lowest validation (selection) loss among seeds 17/29/43; the test split was not consulted. The research delivery recorded PyTorch/NumPy parity for this checkpoint as passed, with max logit error 2.4×10⁻⁷.
- NumPy is now a declared runtime dependency. Previously it was only a development extra, so the packaged runtime had no NumPy and DKT could not load at all. Torch is still excluded from the runtime.

## Shadow policy

- `SourceModelPackage` verifies the following before use: byte size and SHA-256, format, vocabulary and weight dimensions, finite weights, calibration bounds, and a 16-step numeric self-check against an independent float64 reference.
- Only JSON is read. No pickle and no package-supplied code runs.
- A loaded package is always `mode = shadow` and `controls_teaching = false`. The package cannot authorise itself.
- MathTutor skills (for example `linear_isolation`) are not in the ASSISTments vocabulary, and the offline crosswalk (`source_skill_mapping_v1`) is explicitly `runtime_enabled = false`. Every frozen presentation forecast therefore records the shadow model's identity with `probability = null` and `coverage_status = unsupported_target`. No probability is invented for MathTutor tasks.
- If a package is missing or damaged, the service reports `unavailable_fallback`. Learning facts, grading and recommendations keep working.
- `/student-summary` and the learning-state summary now report `dkt_mode = shadow` and `dkt_controls_teaching = false`, plus the shadow model identity. None of this is surfaced as a probability in the UI.

## Packaging

- The package allowlist ships `learning/knowledge_tracing/assets/*/*.json`, and the audit now requires `numpy` in the relocated runtime.
- The Windows runtime was rebuilt from the official Python 3.12.10 embeddable package with `numpy` 2.5.3.

## Validation

- Backend: 1414 passed, 11 skipped. This includes 14 new tests for integrity, reference parity, damaged-package rejection, shadow policy, fallback and shipping.
- In the packaged runtime itself, NumPy imports and the bundled package loads in shadow mode, and its self-check passes.

Not verified: installation and uninstallation on a clean machine, macOS and Linux packages, and any target-domain (MathTutor student) effect of the model. The ASSISTments terms for redistributing derived weights have not been confirmed; see `THIRD_PARTY_NOTICES.md`.

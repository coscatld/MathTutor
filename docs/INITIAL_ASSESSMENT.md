# Initial assessment and verified multiple-choice practice

Work ticket: EXP-W02-003; policy `placement_start_v1`; choice schema `verified_choices_v1`.

## Product behavior

The first transition from an unconfigured provider to a ready configuration with an API key creates an owner-scoped assessment. Successful local credential storage is not proof that the remote provider accepts the key. The onboarding and settings screens use `initial_assessment_required` to navigate to `/onboarding/assessment`; startup resumes unfinished assessment. Existing configured installations are not force-migrated into a test, and key rotation does not reset answers. Keyless Ollama setup is unchanged.

Ten authored single-choice probes cover five broad verifier families (two each): arithmetic, linear equations, polynomial operations, quadratic equations, and linear systems. These are not all thirteen fine-grained curriculum skills and are not a calibrated ability test. Each question has four server-verified choices plus an explicit “unsure” action. Only one question is returned at a time, without an answer key.

The completed result sets a provisional **practice starting difficulty**, not a student level, school grade or mastery probability:

| Observations in one family | Starting difficulty |
| --- | --- |
| Both known and correct | 3/5 |
| Both known and incorrect | 1/5 |
| Mixed answers or any unknown | 2/5 |

Unknown is not incorrect. Skipped/incomplete assessment uses the existing default (2). Skipping is persistent; this version does not offer a retake button. Deleting educational history removes the assessment, after which the learning-profile link allows an explicit new assessment.

The existing practice policy subsequently reads the owner's valid completed observations across sessions. Three different problems with first independent correct answers can raise difficulty one step; three first independent incorrect answers lower it one step. Values stay within 1–5. This is a bounded adjustment relative to the supplied current difficulty, or the initial/default baseline; it is not an indefinitely accumulating proficiency score. Student-requested difficulty and prerequisite teaching purposes retain their existing precedence. Assisted, uncertain, repeated, answer-exposed and later-correction observations do not become first independent evidence. A later correct response cannot replace an earlier incorrect response for the same problem identity.

## Choice delivery and grading

New practice offers require both the existing exact-release verification and successful choice construction. Acceptance persists the choice set/version in the child teaching context. Restart and session projections read the persisted set. The client sends `choice_id` and `choice_version`; the server resolves these against that context and grades the resolved mathematical response through the independent attempt verifier. Forged/stale choice versions fail before an assessed fact is created.

Deterministic rational, polynomial, finite rational-root and assignment choices are checked for exactly one complete correct answer and three incorrect answers. Two rational roots can be submitted as `2, 4`; incomplete root sets remain partial rather than correct. Unsupported answer forms (for example irrational-root distractor generation) fail closed instead of inventing an answer key. An old unaccepted offer whose answer form cannot make choices is rejected with a request for a new invitation; already-active legacy free-response cycles retain their context.

Choice tasks carry `response_format=single_choice`. Their independent observations can inform the explicit rule, but **cannot silently become the existing free-response DKT training target**. Initial answers are stored separately and do not enter DKT state or loss. Neither a selected letter nor the current answer label is a pre-answer model feature.

## Persistence, privacy and APIs

Migration `019_initial_assessment` adds one owner-keyed JSON table (018 remains its parent). The service uses the same server-owned identity key as the facts/privacy repositories, owner locks and compare-and-swap writes. The same run/index/option/version is idempotent; a changed first answer, stale run, wrong owner or deleted record is rejected. No update recreates a deleted row. Educational-history deletion removes assessment facts and revokes pending recommendations whose basis included that run. Desktop startup and macOS packaging probes are aligned with migration head 019.

Under `/api/v2/math-tutor/desktop/initial-assessment`:

- `GET`: read only; missing data returns `not_started`, never creates facts.
- `POST /start`: explicitly ensure a run; does not reset an existing run.
- `POST /answer`: `{run_id, index, option_id, version}`; sequential immutable submissions.
- `POST /skip`: `{run_id}`; preserves the decision to skip.

API keys continue to use the existing secret store and never enter assessment payloads or browser storage. The UI shows only learning observations and policy explanations. Normal security/backup controls for the local learning database remain applicable.

## DKT boundary and future work

Target-domain DKT remains disabled: `probability=null`, reason `unsupported_target_mapping`. The UI explicitly identifies the initial policy as rule-based. This change does not enable a production target model, make every chat message a grade, or conflate assistance L0–L5 with student ability.

A future dialogue-KT adapter must define presentation/task identity, choice version and help exposure before freezing predictions; approve target mappings; validate multiple-choice separately from free response (including guessing); and pass the existing leakage, calibration, student-disjoint evaluation and runtime gates. Updating the old free-response schema merely to make a package load is not sufficient. See [DKT integration research](DKT_INTEGRATION_RESEARCH.md).

## Verification and portability

Run the unchanged cross-platform entry point with the selected Python environment:

```sh
python scripts/check.py
```

`tests/test_initial_assessment.py` covers ten initial items, the five-family/five-difficulty template pool, initial answer persistence/idempotency/isolation/deletion, first-key routing state, real invite difficulty, bounded policy and real WebSocket choice grading. Frontend tests cover routing, public-choice projection, native radio semantics and no client-side grading/credential storage. Engineering tests use synthetic responses, not student efficacy data.

No Windows paths or shell-specific launch commands were added to product code. Existing Linux/macOS/Windows CI and signed-release workflows remain separate. Local browser QA and timestamped full-check evidence are recorded in the sibling experiment directory `research-runs/week02-assessment-20260917`; final CI status must be checked on the exact PR head. A skipped distribution check is not an installer-release pass.

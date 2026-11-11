# Independent learning-loop audit — 2026-11-11

本文保留隔离实验当时的记录；其中 `repo/`、`outputs/`、`audit/` 为本地实验目录。当前源码复现入口与最终验证范围见[概念复查说明](../../11月11号更新文档/002-概念复查与学习闭环.md)。

Scope: isolated experiment source, not the production checkout. No private learner data or paid provider calls. Audit scripts create disposable SQLite databases and use an in-memory secret store for HTTP checks.

## Findings and resolution

1. **Fixed: incompatible probe policies broke reads and export.** `LearningLoopService._public` originally ran today's `diagnostic_state` before checking policy compatibility. A preserved old episode with a removed probe ID raised `ValueError: Unknown probe identity`. The implementation now checks policy first, returns `exhausted/uncertain` with no question and preserves records. Independently rerun `audit/check_boundaries.py` confirms a safe exhausted result. The implementation agent also added API/export/write-rejection regression tests.

2. **Fixed: mixed-policy latency could be misreported as active-policy latency.** The evaluator pooled active, fixed and random measurements. It now records `selection_latency_ms_by_policy`, labels the combined statistic, and excludes no-item decisions. Re-running the same frozen fixtures leaves diagnostic counts and the registered gate unchanged. Active selection p95 in the reviewed run is **0.10125 ms**, 1,400 actual selections; this is a local microbenchmark.

No unresolved blocker was found within this audit scope.

## Independently executed checks

`audit/check_boundaries.py` (real SQLite, injected server clock):

- One microsecond before due: no review question; exact due: review reachable.
- Helped review success does not add independent delayed evidence.
- After a helped failure branch, two review/structural-transfer rounds remain reachable.
- Cross-owner episode lookup and submission are isolated.
- Cancellation after SQL update but before transaction exit rolls back the complete payload.
- Two concurrent identical submissions produce one saved attempt.
- An incompatible old catalog with a removed ID reads safely after the fix.

`audit/check_api_privacy.py` (real product HTTP routes and SQLite with explicit local test transport):

- Public current questions contain no answer/prediction fields.
- Client-supplied independence and time fields are rejected (422).
- Ungradable response leaves the question and evidence counts unchanged.
- Export includes only the caller's whitelisted loop summary.
- Deleting educational history removes that owner's loop and old submissions fail.
- The other owner's episode remains intact; their export cannot see the deleted owner's data.

Results: `audit/results.json`, `audit/api-results.json`, all checks pass. These do not replace full source CI or packaged-app acceptance.

## Interpretation of the offline experiment

- The primary signed-subtraction comparison supports **rule-pattern discrimination under the authored simulator**: active 200/200, seeded random 165/200 within the same three-question budget.
- Fixed ordering is deliberately simple and starts with collision-prone items; the random comparator is more informative than the large gain over fixed order.
- The 200 known cases represent four rule mechanisms with varied available-item exclusions, not 200 independent students. No real-person diagnostic risk interval is justified.
- The separate oracle avoids calling the policy's prediction helper, but still implements the same predefined mathematical mechanisms. This is a controlled consistency/generalization check, not independent cognitive ground truth.
- Strategy changes and observationally identical unknown mechanisms can still match a provisional rule. User-facing labels must stay response-pattern observations; no stable misconception, mastery or learning-gain claim is supported.
- Keeping diagnosis feedback hidden until it ends avoids teaching between measurements. Review/transfer have their own first-response and exposure records.
- The changed-structure probes are missing-operand equations. They test a registered task change; they are not evidence of broad or far transfer.

## Integration note

The current migration target is 025. Pre-upgrade backup filenames use `MIGRATION_HEAD`, so desktop acceptance should search `*pre-025-*`; the historical corrupted input and preserved backup revisions remain 023/024.

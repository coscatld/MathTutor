# Test Migration Matrix

Source inventory: 50 Python specifications under
`DeepTutor/deeptutor/math_tutor/tests/test_*.py`. Result: 41 `MOVED`, 9
`COMPAT_ONLY`, zero silent removals. `benchmark_fixtures.py` moved as a helper
and its one import was rebased to the top-level standalone test directory.

Stage D rebased every `MOVED` specification to the `mathtutor` import package.
The default suite runs against a wheel installed in a clean environment and
passes `571/571`. The nine preserved files remain under
`tests/compat_deeptutor`; their MathTutor imports were rebased, while their
explicit generic-host imports document why they remain `COMPAT_ONLY` and are
excluded by `norecursedirs`.

`COMPAT_ONLY` means the specification directly exercises the optional old
DeepTutor capability/context/stream/auth/current-user adapter. The file is
preserved under `tests/compat_deeptutor` but deliberately excluded from the
standalone default suite. Standalone controller/auth/event behavior is covered
by `test_standalone_decoupling.py`, product API/WS tests and the other moved
domain tests.

| Source specification | Classification | Standalone location / reason |
|---|---|---|
| `test_adaptive_practice.py` | MOVED | `tests/test_adaptive_practice.py` |
| `test_architecture_debt.py` | MOVED | `tests/test_architecture_debt.py` |
| `test_auth_gate.py` | MOVED | `tests/test_auth_gate.py` |
| `test_capability.py` | COMPAT_ONLY | Old `UnifiedContext`/`StreamBus` adapter |
| `test_capability_allowlist.py` | MOVED | `tests/test_capability_allowlist.py` |
| `test_context_assembler.py` | MOVED | `tests/test_context_assembler.py` |
| `test_desktop_bridge.py` | MOVED | `tests/test_desktop_bridge.py` |
| `test_desktop_files.py` | MOVED | `tests/test_desktop_files.py` |
| `test_document_pipeline.py` | MOVED | `tests/test_document_pipeline.py` |
| `test_embedding.py` | MOVED | `tests/test_embedding.py` |
| `test_execution_surface_isolation.py` | COMPAT_ONLY | Imports legacy capability wrapper; standalone closure is enforced in `test_standalone_decoupling.py` |
| `test_gateway_cutover.py` | MOVED | `tests/test_gateway_cutover.py` |
| `test_gateway_secret.py` | MOVED | `tests/test_gateway_secret.py` |
| `test_llm_tutor_writer.py` | COMPAT_ONLY | Imports generic DeepTutor LLM exception compatibility surface |
| `test_math_tutor_ws_auth.py` | COMPAT_ONLY | Exercises old generic auth globals/router monkeypatch boundary |
| `test_nodes.py` | MOVED | `tests/test_nodes.py` |
| `test_owner_scope.py` | COMPAT_ONLY | Exercises old multi-user current-user context fallback |
| `test_parser.py` | MOVED | `tests/test_parser.py` |
| `test_pedagogy_chain.py` | COMPAT_ONLY | Runs pedagogy through old context/stream capability adapter |
| `test_pedagogy_restart_safe.py` | COMPAT_ONLY | Runs restart path through old context/stream capability adapter |
| `test_personal_memory.py` | MOVED | `tests/test_personal_memory.py` |
| `test_phase4_learning.py` | MOVED | `tests/test_phase4_learning.py` |
| `test_phase5_e2e_offer_flow.py` | MOVED | `tests/test_phase5_e2e_offer_flow.py` |
| `test_phase5_practice.py` | COMPAT_ONLY | Contains old `UnifiedContext` capability invocation |
| `test_phase6_backup.py` | MOVED | `tests/test_phase6_backup.py` |
| `test_phase6_backup_policy.py` | MOVED | `tests/test_phase6_backup_policy.py` |
| `test_phase6_curriculum.py` | MOVED | `tests/test_phase6_curriculum.py` |
| `test_phase6_data_lifecycle.py` | MOVED | `tests/test_phase6_data_lifecycle.py` |
| `test_phase6_main_integration.py` | MOVED | `tests/test_phase6_main_integration.py` |
| `test_phase6_observability.py` | MOVED | `tests/test_phase6_observability.py` |
| `test_phase6_outbox_relay.py` | MOVED | `tests/test_phase6_outbox_relay.py` |
| `test_phase6_privacy_wiring.py` | MOVED | `tests/test_phase6_privacy_wiring.py` |
| `test_phase6_product_wiring.py` | MOVED | `tests/test_phase6_product_wiring.py` |
| `test_phase6_relay_loop.py` | MOVED | `tests/test_phase6_relay_loop.py` |
| `test_phase6_retrieval.py` | MOVED | `tests/test_phase6_retrieval.py` |
| `test_phase6_retrieval_benchmark.py` | MOVED | `tests/test_phase6_retrieval_benchmark.py` |
| `test_phase6_retrieval_metadata_first.py` | MOVED | `tests/test_phase6_retrieval_metadata_first.py` |
| `test_phase6_retrieval_reranker.py` | MOVED | `tests/test_phase6_retrieval_reranker.py` |
| `test_product_app.py` | MOVED | `tests/test_product_app.py` |
| `test_product_app_sqlite.py` | MOVED | `tests/test_product_app_sqlite.py` |
| `test_release_config.py` | MOVED | `tests/test_release_config.py` |
| `test_release_probe.py` | MOVED | `tests/test_release_probe.py` |
| `test_retrieval_policy.py` | MOVED | `tests/test_retrieval_policy.py` |
| `test_security_settings.py` | MOVED | `tests/test_security_settings.py` |
| `test_service.py` | MOVED | `tests/test_service.py` |
| `test_solver_verifier.py` | MOVED | `tests/test_solver_verifier.py` |
| `test_sqlite_persistence.py` | COMPAT_ONLY | Exercises persistence through old context/stream capability shell; SQLite behavior remains covered by moved persistence/product suites |
| `test_standalone_decoupling.py` | MOVED | `tests/test_standalone_decoupling.py`; repository path assertions rebased to `src/` |
| `test_state_machine.py` | MOVED | `tests/test_state_machine.py` |
| `test_verifier_worker.py` | MOVED | `tests/test_verifier_worker.py` |

Frontend migration is one-to-one for the seven MathTutor specifications:

- `math-tutor-desktop-lists.test.tsx` → MOVED
- `math-tutor-desktop-panels.test.tsx` → MOVED
- `math-tutor-desktop-settings.test.tsx` → MOVED
- `math-tutor-no-secret-storage.test.tsx` → MOVED
- `math-tutor-offer-navigation.test.tsx` → MOVED
- `math-tutor-practice-offer.test.tsx` → MOVED
- `math-tutor-protocol.test.ts` → MOVED

Stage D frontend result: all seven files are present; together they collect 65
Node assertions, all passing. TypeScript and the production Next build also
pass. No generic product test or route was introduced.

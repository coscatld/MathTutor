# ADR: application-authorized model tools

Status: accepted for this implementation, explicitly authorized by the user on 2026-09-17.

The old expression runtime rejected every model tool call. Knowledge work now needs an actual loop: model proposal → schema/permission/budget validation → application execution → real result receipt → model continuation. A tool request is not a completed answer.

Only search_knowledge, read_source, read_learning_context, verify_math, draft_note, save_note and propose_practice are available. No shell, Python, SQL, arbitrary MCP, web browsing or natural-language code extraction. The ordinary mathematical teaching writer retains its existing disclosure gate and does not gain source/answer access from the knowledge tools. Explicit knowledge mode is separate from exercise mode; active undisclosed answers remain excluded.

The gateway preserves native calls; providers without native support use an explicitly structured JSON proposal contract. Both paths use the same executor, receipts, shared step/token/time budgets and durable save idempotency. New-note saves explicitly authorized by the user's request do not prompt again. Model proposals never authorize overwrite/delete, change source scope, or bypass ReleaseGate. Knowledge/review writes check deletion generations. Existing request journal, cancellation and partial-response contracts remain authoritative.

No claim of real-provider answer quality follows from scripted tests. A provider-free run is NOT_RUN, not PASS. No fake embedding backend is an acceptable production semantic-quality result.

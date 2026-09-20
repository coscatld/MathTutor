# MathTutor 0.4.2 release notes

## Product scope

The supported baseline is local document parsing (including pypdf-readable PDFs), chunking, lexical retrieval, conversation-scoped evidence and traceable citations. Optional embedding dependencies and rich PDF parsing are not part of the guaranteed desktop runtime. OCR for scanned PDFs is not implemented by this release; unsupported/unreadable material must be reported rather than presented as searchable text.

The Knowledge path exposes validated source ranges and distinguishes verbatim quotes from summaries that require support checks. A source-supported statement may still be mathematically wrong. Neither citations, a model stop, nor a finite equation verifier certify an entire natural-language answer.

## Continuation fix and remaining limits

Closed numeric root lists and split parenthesized decimal literals now retain direct textual continuity, including `方程的根为` + `0和-1。`, `(1.` + `5)`, and the LaTeX-delimited equivalent. Recognition is deliberately limited to closed textual productions; it does not verify the listed roots. An added assertion, unfinished suffix, mismatched delimiter or restarted prose remains visibly uncertain/PARTIAL. The existing Continue action remains available for incomplete turns. Output with a `length` stop remains incomplete even when a literal boundary can be joined.

Saved erroneous continuations are retained in offline regressions. No paid Provider calls were made for integration; the cumulative authorized budget stays 75/120 requests and 293690/300000 conservative tokens. Historical AI reviews remain PROVISIONAL_AI, human review remains PENDING, real retesting remains BUDGET_BLOCKED and formal semantic acceptance remains INSUFFICIENT_EVIDENCE. Release engineering does not rewrite the historical quality FAIL.

## Data, upgrade and recovery

Migration head is 023, read from the application migration contract. Before upgrading, create and verify a backup through the existing desktop backup controls; retain the prior installer and backup outside the application install directory. Quit the running application normally before changing versions. User settings, uploaded materials and chat history are not cleared by this integration. Never manually delete an active SQLite WAL/SHM.

Use the application's supported restore flow with a verified compatible backup and version. Restoring an earlier backup can omit subsequently created data: preserve a fresh current backup first and do not silently overwrite new work. A code revert does not revert the database. The release execution record identifies pre-merge main, merged commit, installer hash and validation; a rollback uses a normal revert or a previously verified compatible release, never a force-push.

## Distribution gates

Build only from the confirmed main commit. Validate package surface and the relocated runtime outside the source checkout; keep development fixtures, requests, gateway files and budget ledgers out of resources. The existing Windows local build is unsigned. An unsigned local engineering artifact is not a signed public release: the repository's public packaging workflow requires Authenticode credentials. Missing signing credentials must be recorded as a release blocker, not bypassed.

This repository uses the existing desktop packaging and GitHub release mechanisms; no server deployment, account system or updater is introduced. Platform checks not actually run stay untested. The local execution report records the actual PR, merge, CI, artifact and package smoke outcomes rather than promising a deployment here.

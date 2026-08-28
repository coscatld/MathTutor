# Windows / Linux RC Upgrade and Rollback Runbook

Status: **UNTESTED — NO TARGET MACHINE / NO PREVIOUS INSTALLATION ARTIFACT**.
This is an executable acceptance procedure, not evidence that upgrade works.

## Required inputs

- previous Pre-RC installer/AppImage and its sha256;
- new RC installer/AppImage and its sha256;
- a test user profile containing an existing session, LearningEvidence,
  replayed StudentState, imported document, personal memory, active or consumed
  PracticeOffer and an ExerciseRelease reference;
- the frozen old and new migration heads;
- output path for a machine-readable smoke report.

Never run this procedure against a user's only copy of their data.

## Shared acceptance sequence

1. Launch the previous artifact outside a source checkout.
2. Record the old version, migration head, database checksum and object IDs.
3. Create and verify a product backup through the existing API/UI.
4. Cleanly stop the old app and verify no backend/worker process remains.
5. Replace only the application artifact. Do not move or delete `userData`.
6. Launch the RC and require migration to the frozen head.
7. Require bootstrap `READY` or an explained `DEGRADED` caused only by an
   optional generative/SecretStore surface.
8. Assert the exact old session, evidence, release/practice references,
   documents and memory still exist.
9. Replay StudentState from LearningEvidence and compare it with the persisted
   projection.
10. Run the complete shared `RC_PUBLIC_RELEASE_SMOKE` against the upgraded
    installation, including post-restore solve.
11. Create and verify a new-format backup.

The upgrade is `PASS` only if all eleven assertions and all nineteen shared
smoke assertions pass. Record the old/new artifact hashes in the report.

## Windows x64 procedure

1. Install the previous NSIS package per-user into a path containing spaces and
   Unicode; populate the fixture above.
2. Back up, exit, and confirm no `MathTutor.exe`, owned Python backend, Next
   child, or verifier worker remains.
3. Run the new NSIS installer interactively or silently with `/S`; retain the
   existing `%APPDATA%\MathTutor` data root.
4. Execute `run-windows-release-smoke.ps1` against the new installer and attach
   its JSON report.
5. Verify Authenticode separately. Missing signing credentials remain
   `UNTESTED — MISSING_EXTERNAL_CREDENTIAL`, never PASS.

Rollback after a migration/bootstrap failure:

1. Stop the RC and preserve its logs and failed database for diagnosis.
2. Reinstall the previous signed application binary.
3. Restore the verified pre-upgrade backup through the product restore flow.
4. Do not use the old binary as a database downgrade tool and do not copy an
   active WAL database.
5. Re-run old-version bootstrap and replay consistency checks.

## Linux x64 procedure

1. Make the previous AppImage executable, place it outside the checkout and
   populate the fixture above.
2. Back up, exit and verify no owned child process remains.
3. Replace only the AppImage file; retain `$XDG_CONFIG_HOME/MathTutor` (or the
   Electron-resolved userData path).
4. Run `run-linux-release-smoke.sh` against the new AppImage and attach its JSON
   report.
5. Run once with Secret Service available and once with `secret-tool` absent.
   The absent case must report generative configuration `DEGRADED/BLOCKED` and
   must not create a plaintext credential file.

Rollback uses the same verified-backup rule as Windows: restore through the
product flow after replacing the application binary; never downgrade an active
database file in place.

## Uninstall semantics

Uninstall removes application binaries only. User database, uploads,
documents, backups, memory and logs remain unless a future explicit
"Delete my data" flow obtains a second confirmation. The current NSIS config
has no such deletion option, and AppImage uninstall is deletion of the
AppImage. SecretStore entries are also preserved; automatic credential removal
would require an explicit, separately reviewed user-data deletion contract.

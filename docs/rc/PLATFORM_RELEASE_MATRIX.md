# MathTutor RC Platform Release Matrix

Current state: macOS arm64 unsigned build/package/launch and shared 19-step
public smoke are **PASS**, while signing/notarization keep public release
**PARTIAL**. Windows and Linux are **UNTESTED — NO TARGET MACHINE**. The
NSIS/AppImage configuration and adapters are implemented, but configuration is
not target-machine evidence. The machine-readable authority is
`docs/rc/PLATFORM_RELEASE_MATRIX.json`.

## Evidence rule

The only capability states are `PASS`, `FAIL`, `PARTIAL`, `UNTESTED`, and
`UNSUPPORTED`. `PASS` requires a named artifact hash and an actual run on that
platform. Static tests can establish that a contract exists; they cannot turn a
Windows or Linux cell into `PASS` on this macOS arm64 host.

| Capability | macOS arm64 | Windows x64 | Linux x64 |
|---|---|---|---|
| Build | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Package | PASS (DMG) | UNTESTED — NO TARGET MACHINE (NSIS configured) | UNTESTED — NO TARGET MACHINE (AppImage configured) |
| Install | PASS (readonly DMG mount) | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Launch | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| SecretStore | PASS (real Keychain write/read/delete/final cleanup) | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Verifier Worker | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| SQLite | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Native File Picker | PARTIAL | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Document Import | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Model Config | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Backup | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Restore | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Restart | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Practice E2E | PASS | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Uninstall | UNTESTED | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |
| Upgrade | PASS (frozen pre-RC DMG → final RC) | UNTESTED — NO TARGET MACHINE | UNTESTED — NO TARGET MACHINE |

Separate signing state:

- Windows Authenticode: `UNTESTED — MISSING_EXTERNAL_CREDENTIAL`.
- Linux artifact signing: `UNSUPPORTED — NO_RELEASE_SIGNING_POLICY`.
- Windows public release: `UNTESTED`.
- Linux public release: `UNTESTED`.

## Static implementation audit

The audit was performed on 2026-08-26 from the current checkout.

- Windows has one configured target: NSIS x64. It is per-user
  (`perMachine=false`), supports a custom install directory and has no current
  installer option that silently deletes user data.
- Linux has one configured target: AppImage x64. No deb target is configured;
  AppImage is the only claimed Linux artifact.
- Packaging copies a target-OS Python runtime to `resources/python-runtime` and
  the app imports from `resources/python-app`. This is only a relocation
  design. A copied conda/runtime tree is not proven relocatable until the
  packaged import probe and product smoke pass on its target OS.
- The verifier manager explicitly requests Python `multiprocessing` `spawn`;
  it does not require `fork`. Worker health, timeout, restart and teardown are
  still target-machine assertions.
- Windows Credential Manager uses `advapi32` and in-memory credential blobs.
  Fake-backend unit tests cover write/read/delete/error contracts, but the real
  ABI path remains target-machine `UNTESTED`.
- Linux uses `secret-tool` with the value on stdin. When `secret-tool` is
  absent, availability is false, readiness is `DEGRADED`, key operations fail
  closed, and there is no plaintext fallback. This contract is unit/static
  evidence, not a Linux target-machine PASS.
- Native picking uses Electron `showOpenDialog`, a single explicit file and a
  20 MiB limit. There is no directory scan bridge. GUI behavior is untested on
  Windows and Linux.
- Mutable data is rooted under Electron `userData`; it is outside the app or
  AppImage. The target adapters assert that uninstalling the test installation
  does not remove the isolated user-data sentinel.

## Windows process risk requiring target evidence

`VerifierWorkerManager` is spawn-safe. The Electron shell, however, currently
terminates its direct Python/Next children with `child.kill("SIGTERM")`.
Windows implements this differently from POSIX and the backend itself owns a
spawned verifier process. The target smoke must therefore assert no remaining
`mathtutor-verifier-worker`, Python backend, or Next process after app exit.
Static review cannot close that cell.

## Unified smoke coverage

`RC_PUBLIC_RELEASE_SMOKE` is defined once in
`docs/rc/RC_PUBLIC_RELEASE_SMOKE.json`. Windows and Linux adapters invoke the
same `desktop/scripts/rc-public-release-smoke.js`; platform scripts only handle
install/extract, native SecretStore, signing state and uninstall semantics.

On macOS the final readonly DMG passed all 19 shared assertions, including the
incorrect-attempt non-leak check, document retrieval, complete memory CRUD,
frozen migration head, post-restore solve and orphan-free shutdown. Windows
and Linux use the same driver but remain `UNTESTED` until their target adapters
produce target-machine reports.

## Uninstall and retained user data

The current artifacts do not offer a "Delete my data" option. Removing the
`.app`, NSIS application files, or AppImage must retain the per-user SQLite DB,
documents, backups and Personal Memory under the OS `userData` root. OS
credential items are likewise retained on uninstall; deletion is only through
an explicit product/user action. A future destructive uninstall option must
name each data class and require a second confirmation. This policy is
implemented in the adapters, but actual uninstall behavior remains `UNTESTED`
on the matrix because no complete installer uninstall was executed this round.

## Adapter commands

Windows PowerShell, on a clean Windows 10/11 x64 target:

```powershell
cd C:\src\DeepTutor
npm --prefix desktop ci
npm --prefix web ci
npm --prefix web run build
$env:MATHTUTOR_PYTHON_RUNTIME = "C:\runtime\mathtutor-python-x64"
npm --prefix desktop run package:win
powershell -NoProfile -ExecutionPolicy Bypass -File desktop\scripts\run-windows-release-smoke.ps1 `
  -Installer desktop\dist\MathTutor-0.2.0-win-x64.exe `
  -ReportPath desktop\dist\windows-x64-rc-public-release-smoke.json
```

Run it from a non-admin account whose username contains non-ASCII characters
for those two cells to become PASS. A Unicode/custom install path alone does
not prove the Unicode-username case; the adapter reports an ASCII target user
as `UNTESTED`.

Linux shell, on a clean x86_64 target/VM with FUSE and a Secret Service:

```bash
cd /src/DeepTutor
npm --prefix desktop ci
npm --prefix web ci
npm --prefix web run build
MATHTUTOR_PYTHON_RUNTIME=/opt/mathtutor-python-x64 npm --prefix desktop run package:linux
bash desktop/scripts/run-linux-release-smoke.sh \
  desktop/dist/MathTutor-0.2.0-linux-x86_64.AppImage \
  desktop/dist/linux-x64-rc-public-release-smoke.json
```

Repeat the Linux adapter once in a session where `secret-tool` is unavailable.
The expected result is `BLOCKED` for the sentinel and `DEGRADED` product
readiness, with `plaintext_fallback=false`; it is not an expected PASS.

Adapter exit codes are `0=PASS`, `1=FAIL`, `2=PARTIAL`, `4=wrong/no target
platform`, and `64=usage error`.

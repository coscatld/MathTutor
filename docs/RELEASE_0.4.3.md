# MathTutor 0.4.3 release notes

## Scope

0.4.3 is a presentation release built on the 0.4.2 main line. It changes how the workspace looks and is laid out for primary and secondary school students. Teaching policy, retrieval, citation receipts, the equation verifier, persistence and the database schema are unchanged. Migration head remains 023, so upgrading from 0.4.2 needs no data migration. Still create and verify a backup and quit the app normally before replacing the installer.

## Visual language

- One cool-blue accent on a white canvas, with hairline borders and generous whitespace. Colour marks only what the student can act on or where they are.
- Every colour comes from semantic tokens in `web/app/globals.css`. Components no longer hard-code hex values or Tailwind palette steps.
- `--primary` is a fill that always carries white text. `--primary-text` is the same hue tuned for text and icons. In dark mode they differ, because no single blue reaches 4.5:1 contrast both under white text and on the dark canvas.
- Red, green, amber and rose are reserved for state (error, success, disclosed support, destructive actions).
- System sans-serif fonts (Segoe UI / PingFang SC / Microsoft YaHei) are used, and no web fonts are loaded.
- The design rules are recorded in `design-system/mathtutor/MASTER.md`.

## Layout changes

- An empty conversation places the greeting and composer together at the optical centre. After the first message the composer returns to the bottom.
- Knowledge scope is reached from a header icon. The explicit-mount notice appears in the empty state instead of a permanent bar, which returns the reading height to the transcript.
- The sidebar, composer, student bubbles, tutor avatar and toasts were restyled. Knowledge now has its own icon, distinct from recommended practice.

## Validation

- The backend test suite passes: 1400 passed, 11 skipped. It was run against this tree's `src`.
- Web unit tests pass: 164/164.
- The production Next.js build succeeds.
- The real-Chrome layout smoke passes (mocked HTTP/WS, isolated test data) at 1280×800, 1024×768, 375×812 and 812×375, including dark mode and reduced motion. The smoke's dark-token assertion was updated to the new dark background value; the check itself is unchanged.
- Windows packaging passes distribution runtime relocation and the desktop contract tests.

Not verified: the installer was not installed or uninstalled on a clean machine, macOS and Linux packages were not built, and the release was published without waiting for CI.

## Distribution

The attached Windows x64 NSIS installer is an **unsigned local engineering build**. Windows SmartScreen may warn on first run. It is published as a pre-release, in line with the 0.4.2 distribution gate that an unsigned artifact is not a signed public release.

Known build-host issue: with Node.js 22.20.0 on Windows, `fs.cpSync` crashes (0xC0000409) when the path contains non-ASCII characters. Packaging then fails at the runtime relocation check without printing a reason. Build from an ASCII path, pass an ASCII `-RuntimePath` to `desktop/scripts/build-windows.ps1`, or use the verified Node.js 24.19.0.

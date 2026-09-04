# Runtime resources

The frozen MVP curriculum is currently the code-owned
`StaticCurriculumProvider`; it does not read an external curriculum bundle.
Document ingestion accepts user-selected files at runtime and stores them
under `MATHTUTOR_DATA_ROOT`; no user documents are repository resources.

This directory is reserved for future versioned, redistributable MathTutor
resource packs. No DeepTutor resource bundle or user data was copied during
the extraction.

## Desktop packaging resources

Desktop packages must contain only source-owned, redistributable resources.
Do not add user documents, API keys, credentials, local databases, backups, or
an upstream DeepTutor resource bundle here.

The Windows x64 build prepares its pinned Python 3.12 runtime under
`.runtime/python-win-x64` and writes installers under `desktop/dist`. Both are
generated build outputs and are intentionally excluded from Git. Run
`npm run package:win` from `desktop` to reproduce the NSIS installer.

See [`docs/WINDOWS_BUILD_REPORT.md`](../docs/WINDOWS_BUILD_REPORT.md) for the
verified Windows artifact hash, test results, and remaining release caveats.

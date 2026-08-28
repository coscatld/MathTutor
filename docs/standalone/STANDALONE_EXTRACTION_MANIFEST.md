# Standalone Extraction Manifest

Status: **PASS — final standalone RC candidate source inventory**  
Date: 2026-08-28  
Target: `/Users/mingze/Desktop/大学生计算科学与智能创新/MathTutor`

The authoritative machine inventory is
`STANDALONE_EXTRACTION_MANIFEST.json`. Regenerate it with:

```bash
python scripts/generate_extraction_manifest.py
```

## Package identity

| Surface | Result |
|---|---|
| Distribution | `mathtutor` `0.2.0` |
| Import package | `src/mathtutor` |
| Console command | `mathtutor` |
| Production `import/from deeptutor` | `0` |
| Old source directory | `src/deeptutor` absent |
| Runtime checkout dependency | none |
| Schema/migration | `mt-1` / `006` |

Migrations `001` through `006`, their Alembic environment/template, curriculum
and release constants remain within the installed package. No absolute source
repository path is used at runtime.

## Included surface

| Area | Included basis |
|---|---|
| Python | Product API/controller/domain/application/pedagogy/learning/repositories/infrastructure/security/solving and standalone release entrypoints |
| Persistence | Frozen schema plus Alembic migrations `001`–`006` |
| Tests | 41 default standalone specifications; 9 preserved `COMPAT_ONLY` specifications; no silent removal |
| Web | MathTutor routes, local auth/API bridge, narrow Markdown renderer, seven specifications and minimum lockfile dependency closure |
| Desktop | Electron main/preload, default-deny package allowlist, builder/release scripts, platform contracts and minimal entitlements |
| Docs/scripts | Dependency audit, manifest, architecture, test matrix, RC skeleton and MathTutor release/benchmark scripts |
| Licensing | `LICENSE` and `THIRD_PARTY_NOTICES.md` |

Generic chat, generic RAG, research, agents, tools, subagents, MCP, plugins,
notebook, search, animation and other monorepo product surfaces are excluded.
Third-party framework closures can contain unrelated internal filenames, but
they expose no MathTutor product route or capability. Generated and mutable
content (`node_modules`, `.next*`, `dist`, bytecode, virtual environments,
databases, API keys, documents, backups and logs) is not part of the
deterministic source manifest.

## Dependency contract

Runtime dependencies are limited to the imports used by MathTutor:
`pydantic`, `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`, `fastapi`,
`uvicorn[standard]`, `python-multipart`, `httpx`, `pypdf`, `bcrypt` and
`python-jose[cryptography]`. Development adds only `pytest` and
`pytest-asyncio`.

Frontend runtime dependencies are Next, React, the MathTutor UI icon/Markdown
stack and their lockfile closure. The production route build contains only the
root redirect, auth pages and MathTutor workspace routes.

## Clean environment evidence

A new Python 3.13 environment at
`/tmp/mathtutor-d-clean-zdI3tf/venv` installed this repository as a wheel (not
editable). `PYTHONPATH` and all legacy environment aliases were removed, and no
DeepTutor distribution was installed.

```text
standalone backend: 571 passed, 749 warnings in 20.03s
desktop Python contracts: 3 passed in 0.88s
isolated factory: imported from clean site-packages
isolated loaded deeptutor modules: []
package-surface probe: 119 files / 1,025,424 bytes selected
package-surface observed runtime: 108 mathtutor modules
forbidden source selected: []
```

Warnings are inherited Pytest/FastAPI deprecations and do not change the pass
result.

## Frontend and desktop evidence

```text
frontend node tests: 65 passed
frontend TypeScript: passed
frontend Next production build: passed (9 product/static routes + proxy)
desktop Node contracts: 28 passed with the final artifact enabled
post-package artifact surface: 5 passed
unsigned macOS arm64 package: built
packaged production/auth smoke: passed
packaged app + readonly-DMG full smoke: 17/17 passed each
shared readonly-DMG public business smoke: 19/19 passed
no-API-key degraded smoke: 9/9 passed
frozen pre-RC data-root upgrade: passed
artifact paths named deeptutor: 0
```

The final unsigned local DMG is 180,462,695 bytes with SHA-256
`964e85a0ee7713850b0ccb8eb6d49b246e06dfe51c6e19b8f5a199f7a60e680e`.
It remains test evidence, not a signed public release. Developer ID signing,
notarization/Gatekeeper validation and Windows/Linux target-machine validation
remain external gates. Independent standalone review completed with no P0/P1
after source-manifest and old-host/documentation freeze fixes.

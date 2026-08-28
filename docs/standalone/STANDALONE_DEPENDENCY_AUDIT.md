# MathTutor Standalone Dependency Audit

## Stage D closure — 2026-08-28

The Stage A/B audit has now been closed in the independent repository:

```text
Production import package: mathtutor
Production import/from deeptutor: 0
Runtime DeepTutor distribution dependency: 0
Observed deeptutor modules in isolated wheel factory: 0
Observed deeptutor modules in packaged factory: 0
```

`src/deeptutor` is absent. The source/package allowlist stages only
`python-app/mathtutor`, and the packaged runtime explicitly excludes the old
package and distribution metadata. The historical census below remains intact
as extraction provenance.

## Stage B implementation result — 2026-08-27

The hard-gate implementation has now been completed in the current DeepTutor
checkout; physical extraction and namespace migration have **not** started.

```text
External DeepTutor Runtime Dependencies Count: 10 -> 0
External DeepTutor Source Dependencies Count: 11 -> 0
Observed Transitive External Modules Count: 41 -> 0
Optional legacy adapter import sites: 5 (excluded from product/package path)
```

- `application/controller.py` now owns orchestration and accepts only a
  trusted `MathTutorRequest` plus a typed `MathTutorEventSink`.
- the product WebSocket calls `ProductState.controller` directly through the
  MathTutor-only async event stream;
- `legacy/deeptutor_adapter.py` is the sole optional DeepTutor runtime edge,
  with dependency direction adapter → controller;
- local auth owns JWT/bcrypt/user storage, the six allowlisted auth routes,
  HTTP/cookie and pre-accept WS guards; owner scope is server-derived;
- the TutorWriter type boundary is the local `CompletionClient` Protocol;
- `standalone:create_standalone_app` constructs successfully in a source-only
  `python -I` process, with no external `deeptutor.*` modules in `sys.modules`;
- the default-deny desktop staging policy no longer retains platform core,
  generic auth/config/RAG, runtime, multi-user or Codex OAuth modules.

Permanent enforcement lives in
`tests/test_standalone_decoupling.py` and the package-surface audit.

The remaining sections are the preserved **pre-implementation Stage A
snapshot**; their 11/10/41 counters and `PLANNED_STAGE_B` labels are historical
inputs, superseded by the result above.

> Scope: current DeepTutor checkout, read-only dependency census for Stage A  
> Audit date: 2026-08-27  
> Production code changed: **no**  
> Standalone extraction performed: **no**

## 1. Decision

The current `mathtutor` production source has:

- **15** B-class external DeepTutor import sites;
- **11** unique external module spellings;
- **6** production consumer files;
- after excluding the one `TYPE_CHECKING` import, **14 runtime import sites and
  10 unique runtime module spellings**;
- **41 transitive external DeepTutor modules observed** by the existing clean,
  isolated production-factory import probe.

Therefore the unambiguous Stage A counters are:

```text
External DeepTutor Source Dependencies Count = 11
External DeepTutor Runtime Dependencies Count = 10
Observed Transitive External Modules Count = 41
TARGET = 0
```

`11` is the namespace/source migration gate; `10` is the strict runtime count.
The only difference is the type-only `deeptutor.services.llm.client.LLMClient`
annotation. No external dependency may be excused merely because it happens to
be retained by the current desktop package allowlist.

## 2. Method and evidence

The census used the checkout as the sole source of truth:

```bash
rg -n '(^|\s)(from|import)\s+deeptutor(\.|$)' \
  deeptutor/math_tutor desktop web
```

An AST pass then excluded `mathtutor.*`, separated production from
tests, and marked imports under `if TYPE_CHECKING`. Its exact summary was:

```text
sites 15
unique external module spellings 11
runtime sites 14
unique runtime module spellings 10
consumer files 6
```

The existing package-surface probe is stronger than a source-tree import. It
copies the default-deny allowlist to a temporary source-only staging tree,
launches `python -I` outside the checkout, performs migration, and constructs
the product factory. Evidence:

- `desktop/scripts/audit-package-surface.py`
- `desktop/dist/release-manifest/package-surface-audit.json`
- `status = PASS`
- `selected_source_file_count = 160`
- `observed_runtime_module_count = 148`, of which 107 are MathTutor/root and
  **41 are external DeepTutor modules**
- `forbidden_selected = []`

The result is deliberately reported at three levels. Direct AST dependencies
tell Stage B what must be replaced. The observed 41-module closure tells it
which accidental package-initializer and transitive surfaces must disappear.
Neither figure is inferred from historical architecture documentation.

## 3. Direct import census and replacement plan

Category meanings follow the extraction task: `KEEP_AS_SHARED_CONTRACT`,
`REIMPLEMENT_MINIMAL`, `MOVE_TO_MATHTUTOR`, `REMOVE`, `COMPAT_ONLY`.

| Import | Current Consumer | Why Needed Today | Category | Replacement | Status |
|---|---|---|---|---|---|
| `deeptutor.api.routers.auth.require_auth` | `api/auth_deps.py:50` | HTTP bearer/cookie authentication and current-user installation | `REIMPLEMENT_MINIMAL` | Standalone auth dependency over MathTutor-owned JWT/password/user store; return a MathTutor `PrincipalScope`/`StudentOwnerScope` directly | `PLANNED_STAGE_B` |
| `deeptutor.api.routers.auth.{ws_auth_failed,ws_require_auth}` | `api/auth_deps.py:73` | WS authentication before `accept()` | `REIMPLEMENT_MINIMAL` | Standalone WS guard with the same fail-closed 4001 behavior and request-local identity cleanup | `PLANNED_STAGE_B` |
| `deeptutor.multi_user.context.get_current_user_or_none` | `api/auth_deps.py:80` | Recover the authenticated WS identity from a DeepTutor `ContextVar` | `REIMPLEMENT_MINIMAL` | Auth guard constructs owner scope itself, or a MathTutor-owned request `ContextVar`; never resolve a client-supplied owner | `PLANNED_STAGE_B` |
| `deeptutor.core.context.UnifiedContext` | `api/math_tutor_ws.py:24` | Adapts the product WS envelope into the old capability API | `COMPAT_ONLY` | WS builds a narrow immutable `MathTutorRequest` and calls `MathTutorController`; `UnifiedContext` remains only in an optional legacy DeepTutor adapter | `PLANNED_STAGE_B` |
| `deeptutor.core.stream_bus.StreamBus` | `api/math_tutor_ws.py:25` | Bridges capability events to the product WS | `REIMPLEMENT_MINIMAL` | MathTutor-owned typed event sink/async stream over existing student-public event schemas; no tool/thinking/general event surface | `PLANNED_STAGE_B` |
| `deeptutor.api.routers` (`auth` submodule) | `api/product_app.py:91` | Copies six allowlisted routes from the monolithic DeepTutor auth router | `REIMPLEMENT_MINIMAL` | Mount a dedicated standalone auth router containing only status/login/logout/register/is-first-user/profile | `PLANNED_STAGE_B` |
| `deeptutor.services` (`auth` submodule) | `api/product_app.py:121` | Reads `AUTH_ENABLED`/`AUTH_SECRET` from DeepTutor auth globals | `REIMPLEMENT_MINIMAL` | MathTutor-owned auth service/settings object injected into the app factory; avoid import-time globals | `PLANNED_STAGE_B` |
| `deeptutor.services.config.load_auth_settings` | `api/product_app.py:122` | Reads bootstrap password/auth posture | `REIMPLEMENT_MINIMAL` | Narrow MathTutor auth settings loader under the standalone data root; no generic provider/RAG config package import | `PLANNED_STAGE_B` |
| `deeptutor.core.capability_protocol.{BaseCapability,CapabilityManifest}` | `capabilities/math_tutor.py:38` | Makes the whole MathTutor orchestration a DeepTutor selectable capability | `COMPAT_ONLY` | Extract orchestration into `MathTutorController`; optional `DeepTutorMathTutorAdapter` subclasses `BaseCapability` and only translates request/events | `PLANNED_STAGE_B` |
| `deeptutor.core.context.UnifiedContext` | `capabilities/math_tutor.py:39` | Carries session/message/owner metadata into the capability | `COMPAT_ONLY` | Controller accepts only MathTutor request + trusted owner scope; no knowledge/tool/capability fields | `PLANNED_STAGE_B` |
| `deeptutor.core.stream.{StreamEvent,StreamEventType}` | `capabilities/math_tutor.py:40` | General runtime envelope used for emitted content/error | `MOVE_TO_MATHTUTOR` | Emit MathTutor-owned public event DTOs already constrained by `pedagogy/events.py`; keep a translator only in legacy adapter | `PLANNED_STAGE_B` |
| `deeptutor.core.stream_bus.StreamBus` | `capabilities/math_tutor.py:41` | General event fan-out passed throughout the current orchestration | `REIMPLEMENT_MINIMAL` | Narrow event-sink Protocol (`emit` or callback) owned by MathTutor; it must not expose tool calls, observations, or wait-for-input | `PLANNED_STAGE_B` |
| `deeptutor.services.llm.client.LLMClient` | `pedagogy/tutor_writer.py:33` | Type annotation for the injected completion client; not imported at runtime | `REIMPLEMENT_MINIMAL` | Local structural `CompletionClient` Protocol containing only the tested `complete(...)` call | `TYPE_CHECKING_ONLY / PLANNED_STAGE_B` |
| `deeptutor.multi_user.paths.{LOCAL_ADMIN_ID,LOCAL_ADMIN_USERNAME}` | `security/scopes.py:27` | Fixed server-generated loopback development identity | `MOVE_TO_MATHTUTOR` | Freeze equivalent constants in MathTutor identity/config; retain dev/test + loopback-only gate | `PLANNED_STAGE_B` |
| `deeptutor.multi_user.context.get_current_user_or_none` | `security/scopes.py:93` | Legacy fallback when capability context did not carry an owner | `COMPAT_ONLY` | Standalone controller requires explicit trusted owner; legacy adapter may translate DeepTutor current user into MathTutor scope without reverse imports | `PLANNED_STAGE_B` |

No entry is `KEEP_AS_SHARED_CONTRACT`: the target repository cannot require a
DeepTutor package. Frozen semantics may be retained, but ownership of every
required contract must move to MathTutor or be represented by a minimal local
Protocol.

### 3.1 Complete A/B classification, including tests and shells

The AST classification of every Python import in the requested directories is:

| Scope | A class: `mathtutor.*` | B class: other `deeptutor.*` | Treatment |
|---|---:|---:|---|
| MathTutor production | 462 | 15 | A is mechanical namespace migration; B is the replacement table above |
| MathTutor tests | 390 | 24 | A migrates mechanically; B is test compatibility debt, not runtime dependency |
| Desktop Python scripts/tests | 19 | 0 | Mechanical namespace migration only |
| Web Python | 0 | 0 | No Python DeepTutor import dependency |

The 24 test-only B sites use seven unique modules:
`deeptutor.core.context`, `deeptutor.core.stream_bus`,
`deeptutor.services.llm.exceptions`, `deeptutor.api.routers.auth`,
`deeptutor.services.auth`, `deeptutor.services` (the `auth` submodule), and
`deeptutor.multi_user.context`. They occur in eight test files:
`test_capability.py`, `test_llm_tutor_writer.py`,
`test_math_tutor_ws_auth.py`, `test_owner_scope.py`,
`test_pedagogy_chain.py`, `test_pedagogy_restart_safe.py`,
`test_phase5_practice.py`, and `test_sqlite_persistence.py`.

These imports do not change the 11/10 production counters. In Stage B, tests of
standalone behavior must move to the new local controller/auth/event contracts;
tests deliberately covering `DeepTutorMathTutorAdapter` must be isolated as
legacy compatibility tests and must not ship in the standalone package.

## 4. Replacement groups and dependency direction

### 4.1 Controller / capability shell

The orchestration currently lives inside `MathTutorCapability`, so core
business logic inherits four generic runtime contracts. Stage B must create a
MathTutor-owned controller/facade first, while files are still in this repo:

```text
Standalone FastAPI / WS
        -> MathTutorController
        -> MathTutorApplicationService and existing deterministic services

Optional DeepTutorMathTutorAdapter
        -> MathTutorController
```

The forbidden reverse edge is
`MathTutorController -> ChatOrchestrator/CapabilityRegistry/BaseCapability`.
The adapter may translate `UnifiedContext` and generic `StreamBus`; the
standalone product path may not know they exist.

### 4.2 Auth and owner scope

`PrincipalScope` and `StudentOwnerScope` are already MathTutor-owned and should
remain the trusted boundary. Reimplement only the minimum surrounding surface:

- JWT creation/verification and bcrypt password verification;
- local user store and first-user registration semantics;
- HTTP bearer/cookie and WS-before-accept guards;
- request-local current identity only if needed by auth handlers;
- the six allowlisted auth routes;
- standalone runtime/data-root resolution.

Do not copy DeepTutor admin user management, PocketBase, Codex OAuth callback,
generic grants/workspaces, partner scopes, provider catalogs, or generic config
loaders. Owner composite FK, `student_id`, owner isolation, and fixed loopback
dev identity remain mandatory.

### 4.3 Events and streaming

The current general `StreamEventType` contains tool, thinking, observation,
source, and wait-for-input events that the student product intentionally drops.
The standalone contract should contain only MathTutor public events and turn
termination/error behavior. The existing `StudentPublicEvent` serializer is the
semantic source to move/keep; do not clone the generic StreamBus wholesale.

### 4.4 LLM boundary

`LLMClient` is only a type-checking import. Runtime generation already enters
through `GenerativeModelGateway` and an injected role client. Replace the type
with a minimal local Protocol. This preserves the rule that the LLM can express
authorized content but cannot judge, verify, release, write evidence/mastery,
or choose state transitions.

## 5. Observed transitive import closure

The clean production factory currently loads these **41** external modules:

```text
deeptutor.api
deeptutor.api.routers
deeptutor.api.routers.auth
deeptutor.core
deeptutor.core.capability_protocol
deeptutor.core.context
deeptutor.core.stream
deeptutor.core.stream_bus
deeptutor.core.tool_protocol
deeptutor.core.trace
deeptutor.multi_user
deeptutor.multi_user.context
deeptutor.multi_user.models
deeptutor.multi_user.paths
deeptutor.runtime
deeptutor.runtime.home
deeptutor.runtime.mode
deeptutor.services
deeptutor.services.auth
deeptutor.services.codex_auth
deeptutor.services.codex_auth.catalog
deeptutor.services.codex_auth.constants
deeptutor.services.codex_auth.contracts
deeptutor.services.codex_auth.oauth
deeptutor.services.codex_auth.service
deeptutor.services.codex_auth.storage
deeptutor.services.config
deeptutor.services.config.embedding_endpoint
deeptutor.services.config.knowledge_base_config
deeptutor.services.config.launch_settings
deeptutor.services.config.loader
deeptutor.services.config.model_catalog
deeptutor.services.config.origins
deeptutor.services.config.runtime_settings
deeptutor.services.file_io
deeptutor.services.path_service
deeptutor.services.rag
deeptutor.services.rag.factory
deeptutor.services.rag.file_routing
deeptutor.services.rag.provider_binding
deeptutor.services.rag.service
```

This list is not a recommendation to move 41 modules. It exposes accidental
coupling:

- importing `deeptutor.core.context` executes `deeptutor.core.__init__`, which
  also loads tool protocol and trace contracts that MathTutor does not use;
- the monolithic auth router imports Codex OAuth even though the MathTutor
  product excludes that route;
- asking generic `services.config` only for auth settings imports knowledge-base
  configuration and generic RAG modules;
- multi-user paths pull generic runtime-home/path-service packages.

Stage B must reduce this closure, not reproduce it in the standalone tree.

## 6. Focus-area verdicts

| Focus area | Direct B import | Observed factory import | Standalone decision |
|---|---:|---:|---|
| `ChatOrchestrator` | 0 | 0 | `REMOVE`; explicitly forbidden by package allowlist |
| `runtime/bootstrap` / capability registry | 0 | 0 | `REMOVE`; MathTutor's own desktop bootstrap tracker is unrelated and remains internal |
| `StreamBus` | 2 sites | yes | `REIMPLEMENT_MINIMAL` as MathTutor-only typed event sink |
| `LLMClient` | 1 type-only site | no | local structural Protocol |
| auth/JWT | 5 direct sites across router/service/config spellings | yes | `REIMPLEMENT_MINIMAL`, preserving fail-closed behavior |
| `PrincipalScope` / owner scope | already MathTutor-owned | context/path helpers observed | keep MathTutor scopes; remove generic current-user/path dependency |
| settings | auth settings directly; generic config transitively | yes | narrow MathTutor loaders; remove generic config/RAG side effects |
| logging | 0 (`logging` is stdlib) | 0 `deeptutor.logging` | use stdlib/local observability; do not copy generic logging stack |
| event types | 1 direct site | yes | `MOVE_TO_MATHTUTOR` public event DTO only |
| generic memory | 0 | 0 | `REMOVE`; keep MathTutor Personal Memory implementation only |
| generic RAG | 0 | yes, accidental config closure | `REMOVE`; keep MathTutor retrieval policy/repositories only |
| generic tools/plugins/MCP | 0 | 0 | `REMOVE`; forbidden by package allowlist |
| agents/research/subagent | 0 | 0 | `REMOVE`; forbidden by package allowlist |
| Manim/math animator | 0 | 0 | `REMOVE`; forbidden by package allowlist |

## 7. `package_allowlist.json` conclusions

The allowlist is positive evidence that public MathTutor runtime already works
without the broad monorepo surface. It explicitly forbids artifact paths for:

- `agents`, `tools`, general `capabilities`, and runtime orchestrator/registry;
- `book`, `co_writer`, `partners`;
- MCP, sandbox, search, session, subagent, notebook, media generation and other
  generic services.

It currently retains platform-core files only because the direct imports above
still exist. That retained list is a migration input, not permission to copy the
platform into standalone. In particular, generic RAG appearing in the observed
closure is an import-side-effect debt and does not override the source census:
MathTutor has no direct external generic-RAG import.

## 8. Stage B hard gates

Stage B is complete only when all of the following are true:

1. **Controller ownership:** core orchestration is callable through a
   MathTutor-owned controller/facade that does not subclass or import any
   DeepTutor runtime/capability class.
2. **Dependency direction:** any legacy adapter imports the controller; no
   MathTutor controller/application/domain/infrastructure module imports the
   adapter, ChatOrchestrator, registry, `deeptutor.core`, or generic services.
3. **AST zero gate:** outside one explicitly named legacy adapter package,
   production MathTutor source has zero B-class imports. The eventual standalone
   source has zero `import deeptutor` / `from deeptutor` of any kind.
4. **Isolated factory gate:** a temporary source-only staging tree containing
   MathTutor code (plus third-party dependencies, no DeepTutor modules) can run
   migration and construct the production app under `python -I`, outside the
   checkout, with no checkout import leakage.
5. **Runtime module gate:** standalone factory/controller smoke leaves no
   `deeptutor.*` module in `sys.modules`; ChatOrchestrator, registry, generic
   tools/agents/plugins/MCP/research/animator are specifically asserted absent.
6. **Auth gate:** registration/login/status/profile, HTTP bearer/cookie, WS
   pre-accept rejection, production auth-on startup, weak-secret rejection,
   dev loopback-only fallback, and two-owner isolation retain negative tests.
7. **Event gate:** standalone WS emits only MathTutor public schemas; internal
   solution/candidate/verification/trace/tool fields remain structurally absent.
8. **Invariant regression:** Parser/Solver/Verifier, verifier-worker typed JSON
   IPC/isolation/timeout/hard-kill/budget/backpressure/fail-closed, LearningEvidence
   projection, release chain, WAL/UoW/CAS/outbox, migrations 001-006, backup and
   restore maintenance gate all remain unchanged and pass the frozen suite.
9. **Secret gate:** API keys remain OS-credential-store-only; no `.env`, normal
   config, SQLite, localStorage, argv, log, or source fallback appears.
10. **Package gate:** the standalone package manifest is default-deny and its
    forbidden-path assertions remain zero; no module excluded by the current
    allowlist may be reintroduced without a new direct import proof and review.
11. **Embedding gate:** concrete embedding model/sqlite-vec production wiring
    remains absent; distribution status stays `PROPOSED / DEFERRED`.
12. **Regression gate:** frozen MathTutor 702/702 baseline and the relevant
    auth/runtime, frontend, distribution, worker/restore, embedding, packaged
    smoke, no-key and upgrade suites must not regress.

Stage C/D physical extraction and namespace migration must not begin in bulk
until these gates are met. The first measurable Stage B target is:

```text
External DeepTutor Runtime Dependencies Count: 10 -> 0
External DeepTutor Source Dependencies Count: 11 -> 0
```

## 9. Risks for Stage B

- **Highest risk — auth copy by accretion:** copying the existing auth router
  would silently bring admin, PocketBase and Codex OAuth dependencies. Build a
  six-route standalone router from minimal contracts instead.
- **High risk — controller extraction breadth:** the current 900+ line
  capability contains the deterministic tutoring orchestration. Move behavior
  without rewriting Parser/Solver/Verifier/Student Model/Practice semantics.
- **High risk — owner fallback:** replacing the ContextVar must not introduce an
  anonymous/default owner or accept identity from a request envelope.
- **Medium risk — event compatibility:** public WS ordering, `turn_end`, replay,
  error projection and disclosure filtering must remain byte/contract compatible.
- **Medium risk — package initializer illusion:** a source import can appear
  narrow but execute a broad `__init__`; keep the isolated `sys.modules` probe as
  a permanent CI gate.
- **Medium risk — legacy adapter inversion:** convenience imports from the new
  controller back into DeepTutor runtime would recreate the original coupling.

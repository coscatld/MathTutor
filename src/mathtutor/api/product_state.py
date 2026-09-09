"""Product-level runtime state shared by the WS and read routers.

One :class:`MathTutorController` + one session store per process.

Phase 1: with a db path the state is durable (SQLite: authoritative cycle
records, CAS, owner isolation); without one it runs fully in memory (tests,
dev loop). The controller sees only the SessionStoreProtocol — storage is a
construction detail.

Phase 5/6 knowledge surface (this round): the product ALSO owns the
personal-memory KG, the user-document pipeline (controlled storage +
parser + chunker + optional vector index) and the generative gateway.
Construction rules:

- the generative gateway is built over the SecretStore; NO API key ever
  appears in this module (keys live in the store — OS credential store
  in the shipped desktop app);
- the embedding runtime starts WITHOUT a backend; an explicitly enabled,
  complete local/cloud setting may attach one later. Documents always retain
  lexical retrieval and vector indexing remains optional/best-effort;
- SQLite mode wires the knowledge repositories to the same database;
  in-memory mode keeps process-local implementations;
- the ContextAssembler is the ONLY path from these repositories to LLM
  consumers (writer/practice generators).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from mathtutor.application.adaptive_practice import AdaptivePracticeService
from mathtutor.application.context_assembler import (
    ContextAssembler,
    MisconceptionSourceProvider,
    PersonalMemorySourceProvider,
    RecentAttemptsSourceProvider,
    StaticCurriculumProvider,
    StudentModelSourceProvider,
    UserDocumentsSourceProvider,
)
from mathtutor.application.document_ingestion import (
    DocumentIndexManager,
    DocumentIngestionService,
)
from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.verification_backend import (
    InProcessVerificationBackend,
    VerificationBackend,
)
from mathtutor.application.personal_memory_service import PersonalMemoryService
from mathtutor.application.controller import MathTutorController
from mathtutor.domain.retrieval_policy import RetrievalSource
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime
from mathtutor.infrastructure.gateway_config import GatewayConfigService, build_tutor_writer
from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole
from mathtutor.infrastructure.secret_store import (
    InMemorySecretStore,
    SecretStore,
)
from mathtutor.pedagogy.writer_settings import (
    load_math_tutor_writer_settings,
)
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from mathtutor.repositories.document_repository import InMemoryDocumentRepository
from mathtutor.repositories.memory_repository import InMemoryMemoryRepository
from mathtutor.repositories.session_store import (
    InMemorySessionStore,
    SessionStoreProtocol,
)


def _build_writer(gateway: GenerativeModelGateway, personality_instruction: str = ""):
    """LLM writer through the generative gateway; template otherwise.

    Fail-closed (Phase 5 cutover): the writer is built only when the
    TUTOR_WRITER role is registered AND its model is resolved AND
    MATHTUTOR_WRITER_ENABLED; every other path — disabled, unconfigured,
    unreachable, unexpected error — yields the deterministic template
    writer (model problems can never break the teaching flow, Phase 3 A3).
    """
    settings = load_math_tutor_writer_settings()
    provider = gateway.provider_for(ModelRole.TUTOR_WRITER)
    if provider is not None and provider.model:
        settings = settings.model_copy(update={"enabled": True, "model": provider.model})
    settings = settings.model_copy(update={"personality_instruction": personality_instruction})
    return build_tutor_writer(gateway, settings)


#: Desktop boot sequence (wire contract: /api/v2/math-tutor/desktop/bootstrap).
#: Key → friendly Chinese label; the order IS the boot order.
BOOT_STEPS: tuple[tuple[str, str], ...] = (
    ("check_data_root", "数据目录"),
    ("database", "数据库"),
    ("migration", "数据库迁移"),
    ("verifier_worker", "数学验证器"),
    ("secret_store", "凭据库"),
    ("document_storage", "文档存储"),
    ("curriculum", "课程目录"),
    ("retrieval", "检索服务"),
    ("outbox", "事件分发"),
    ("model_gateway", "AI 模型网关"),
)

_BOOT_STEP_LABELS: dict[str, str] = dict(BOOT_STEPS)


class BootstrapTracker:
    """Records the nine-step boot sequence once per process (startup hook).

    Read by GET /bootstrap: while booting, ``phase`` is the current step key
    ("STARTING" before the first step, "READY" after finish); ``readiness``
    and ``reason`` derive from the step statuses. Labels/details are friendly
    Chinese text by construction — no internals ever leave this tracker.
    """

    def __init__(self) -> None:
        self._finished = False
        self._phase = "STARTING"
        self._steps: dict[str, dict] = {}

    def record(self, key: str, status: str, detail: str | None = None) -> None:
        """Record one step ("ok" | "degraded" | "blocked")."""
        self._steps[key] = {
            "key": key,
            "label": _BOOT_STEP_LABELS.get(key, key),
            "status": status,
            "detail": detail,
        }
        self._phase = key

    def finish(self) -> None:
        """Mark the boot sequence complete (the endpoint then serves the
        final snapshot; the phase becomes "READY")."""
        self._finished = True
        self._phase = "READY"

    def snapshot(self) -> dict:
        """Wire-contract BootstrapPayload dict (see desktop/types.ts)."""
        steps = [self._steps[key] for key, _ in BOOT_STEPS if key in self._steps]
        blocked = [s for s in steps if s["status"] == "blocked"]
        degraded = [s for s in steps if s["status"] == "degraded"]
        if not self._finished:
            readiness, reason = "BLOCKED", "应用正在启动，请稍候。"
        elif blocked:
            readiness, reason = "BLOCKED", blocked[0]["detail"]
        elif degraded:
            readiness, reason = "DEGRADED", degraded[0]["detail"]
        else:
            readiness, reason = "READY", None
        return {
            "readiness": readiness,
            "phase": self._phase,
            "reason": reason,
            "steps": steps,
        }


#: Desktop-mode contract env var (set by the Electron shell, desktop/main.js).
#: Single source of truth for the SecretStore decision below.
DESKTOP_MODE_ENV = "MATHTUTOR_DESKTOP"

_DEV_OR_TEST_ENVIRONMENTS = frozenset({"development", "test"})


def _default_secret_store() -> SecretStore:
    """OS credential store in desktop production; in-memory everywhere else.

    Desktop production = ``MATHTUTOR_DESKTOP=1`` (Electron shell) AND the
    security environment not development/test. The gateway binds its key
    resolver to this SAME instance at construction, so the settings surface
    and generation-time key resolution must share ONE store — a key saved to
    the OS credential store would otherwise be unresolvable by the gateway
    (desktop secret-store wiring; see the desktop bridge tests).
    """
    import os

    from mathtutor.infrastructure.keychain_secret_store import (
        KeychainSecretStore,
    )
    from mathtutor.security.settings import (
        load_math_tutor_security_settings,
    )

    if os.environ.get(DESKTOP_MODE_ENV) in {"1", "true", "yes", "on"}:
        environment = load_math_tutor_security_settings().environment
        if environment not in _DEV_OR_TEST_ENVIRONMENTS:
            return KeychainSecretStore()
    return InMemorySecretStore()


class ProductState:
    """The student product's single tutoring runtime."""

    def __init__(
        self,
        store: SessionStoreProtocol | None = None,
        service: MathTutorApplicationService | None = None,
        *,
        engine=None,
        data_dir: Path | None = None,
        db_path: Path | None = None,
        secret_store: SecretStore | None = None,
        embedding_runtime: EmbeddingRuntime | None = None,
        verification_backend: VerificationBackend | None = None,
    ) -> None:
        self.store: SessionStoreProtocol = store or InMemorySessionStore()
        # Request-level maintenance barrier.  Restore is the only operation
        # that replaces the live SQLite file; it first closes this gate, waits
        # for already-admitted HTTP/WebSocket requests to drain, and keeps it
        # closed through verify/copy/migrate/rollback.  Background writers are
        # stopped separately by ``shutdown_runtime``.
        self._maintenance_condition = asyncio.Condition()
        self._active_requests = 0
        self._maintenance_active = False

        # ---- Phase 5/6 knowledge surface -------------------------------
        # The gateway is built FIRST so the capability's writer can be
        # resolved through it (TUTOR_WRITER role; fail-closed template).
        self.secret_store: SecretStore = secret_store or _default_secret_store()
        self.gateway = GenerativeModelGateway(self.secret_store)
        # No embedding backend by default. User settings may replace it only
        # after an explicitly selected local/cloud configuration is ready.
        self.embedding_runtime = embedding_runtime or EmbeddingRuntime()
        # Durable/product mode uses one killable verifier process.  The
        # in-process backend is an explicit development/test profile only;
        # production never falls back to it after a worker failure.
        if verification_backend is None:
            if engine is not None:
                from mathtutor.infrastructure.verifier_worker import (
                    VerifierWorkerManager,
                )

                verification_backend = VerifierWorkerManager()
            else:
                verification_backend = InProcessVerificationBackend()
        self.verification_backend = verification_backend
        if service is None:
            service = MathTutorApplicationService(
                verification_backend=self.verification_backend
            )
        else:
            service.verification_backend = self.verification_backend
        # The product database file (None in in-memory mode) — the backup
        # restore orchestration needs it to stop→dispose→restore→rebuild.
        if db_path is not None:
            self.db_path: Path | None = Path(db_path)
        elif engine is not None and engine.url.database:
            self.db_path = Path(engine.url.database)
        else:
            self.db_path = None
        # Desktop boot sequence record (GET /bootstrap). The app factory's
        # startup hook fills it; before that the snapshot reads "booting".
        self.bootstrap_tracker = BootstrapTracker()

        if engine is not None:
            from mathtutor.repositories.sqlite_curriculum import (
                SQLiteCurriculumRepository,
            )
            from mathtutor.repositories.sqlite_knowledge import (
                SQLiteDocumentRepository,
                SQLiteMemoryRepository,
            )
            from mathtutor.repositories.sqlite_practice import (
                SQLitePracticeRepository,
            )
            from mathtutor.repositories.uow import MathTutorUow
            from mathtutor.repositories.conversation_repository import SQLiteConversationRepository

            # The UoW wakes the resident outbox relay after every committed
            # transaction (best-effort accelerator; the loop also polls).
            # ``_relay_wake`` reads the relay lazily — it does not exist yet
            # during the first repository constructions below.
            self.uow = MathTutorUow(engine, on_commit=self._relay_wake)
            self.memory_repository = SQLiteMemoryRepository(engine)
            self.document_repository = SQLiteDocumentRepository(engine)
            self.practice_repository = SQLitePracticeRepository(self.uow)
            self.curriculum_repository = SQLiteCurriculumRepository(self.uow)
            self.conversations = SQLiteConversationRepository(engine)
        else:
            from mathtutor.repositories.practice_repository import (
                InMemoryPracticeRepository,
            )
            from mathtutor.repositories.sqlite_curriculum import (
                InMemoryCurriculumRepository,
            )
            from mathtutor.repositories.conversation_repository import InMemoryConversationRepository

            self.uow = None
            self.memory_repository = InMemoryMemoryRepository()
            self.document_repository = InMemoryDocumentRepository()
            self.practice_repository = InMemoryPracticeRepository()
            self.curriculum_repository = InMemoryCurriculumRepository()
            self.conversations = InMemoryConversationRepository()

        # Phase 5 verified-release catalog: offers/accepts go through this
        # repository ONLY (the store's accept transaction re-validates the
        # offer with a CAS against the same rows). The capability receives
        # it at construction so offer accept is restart-safe.
        from mathtutor.application.practice_release import (
            ExerciseReleaseService,
        )

        self.exercise_release = ExerciseReleaseService(
            self.practice_repository,
            verification_backend=self.verification_backend,
        )
        # Phase 6 (first round): versioned curriculum catalog + the outbox
        # relay. The relay is SQLite-only (it reads domain_outbox through a
        # UoW); in-memory mode keeps it None. Scheduling the relay loop is
        # the app factory's job (startup hook, idempotent + restart-safe).
        from mathtutor.application.curriculum_catalog import (
            CurriculumCatalogService,
        )

        self.curriculum = CurriculumCatalogService(self.curriculum_repository)
        if self.uow is not None:
            from mathtutor.application.outbox_relay import (
                OutboxRelayService,
            )

            self.outbox_relay = OutboxRelayService(self.uow)
        else:
            self.outbox_relay = None
        # The capability is constructed LAST (after adaptive_practice) so it
        # receives the practice service for the server-driven offer flow
        # (§7.5 E2E: solved → reflected → practice_offered → accept).

        # Controlled document storage: durable mode uses the db's data dir;
        # in-memory mode gets a private temp dir (process-lifetime).
        if data_dir is None:
            self._tmp_uploads = tempfile.TemporaryDirectory(prefix="mathtutor-uploads-")
            data_dir = Path(self._tmp_uploads.name)
        else:
            self._tmp_uploads = None
        self.document_storage = DocumentStorage(data_dir)
        # One provider-config service owns restore, persistence and key
        # references for the lifetime of the product.  Restoring here (before
        # the controller writer is built) makes an existing secure provider
        # configuration effective immediately after restart.
        self.gateway_config = GatewayConfigService(
            gateway=self.gateway,
            secret_store=self.secret_store,
            config_path=Path(data_dir) / "gateway.json",
        )
        from mathtutor.infrastructure.embedding_config import EmbeddingConfigService

        self.embedding_config = EmbeddingConfigService(
            data_dir=Path(data_dir),
            secret_store=self.secret_store,
            runtime=self.embedding_runtime,
        )
        from mathtutor.infrastructure.tutor_preferences import TutorPreferenceService

        self.tutor_preferences = TutorPreferenceService(Path(data_dir) / "tutor.json")

        # Phase 6 (round 2): backup/restore surface. SQLite-only (the file
        # is the unit of backup). Policy: manual mode — the desktop UI
        # triggers backups; the scheduler is built but NOT started here
        # (the startup hook / restore orchestration own its lifecycle).
        # Backups live in a controlled subdirectory of the data dir.
        if self.uow is not None:
            from mathtutor.infrastructure.backup import (
                BackupPolicy,
                BackupScheduler,
                BackupService,
            )

            self.backup_service = BackupService(engine)
            self.backup_policy = BackupPolicy(
                mode="manual",
                backup_dir=Path(data_dir) / "backups",
                retention_limit=5,
            )
            self.backup_scheduler = BackupScheduler(
                self.backup_service, self.backup_policy
            )
        else:
            self.backup_service = None
            self.backup_policy = None
            self.backup_scheduler = None

        self.personal_memory = PersonalMemoryService(self.memory_repository)
        self.document_index = DocumentIndexManager(
            repository=self.document_repository,
            embedding_runtime=self.embedding_runtime,
        )
        self.documents = DocumentIngestionService(
            repository=self.document_repository,
            storage=self.document_storage,
            index_manager=self.document_index,
        )
        self.context_assembler = self._build_context_assembler(engine)
        # Phase 5 (§7.4/§7.5): bank > template > LLM generator chain — the
        # gateway's PRACTICE_GENERATOR role when configured, deterministic
        # template otherwise; every candidate still passes the release gate.
        from mathtutor.application.llm_candidate_generator import (
            PracticeGeneratorChain,
        )

        self.adaptive_practice = AdaptivePracticeService(
            assembler=self.context_assembler,
            generator=PracticeGeneratorChain(gateway=self.gateway),
            release_service=self.exercise_release,
        )
        self.controller = MathTutorController(
            store=self.store,
            service=service,
            writer=_build_writer(self.gateway, self.tutor_preferences.instruction()),
            practice_repository=self.practice_repository,
            practice_service=self.adaptive_practice,
            chat_responder=TutorChatResponder(
                self.gateway, self.tutor_preferences.instruction()
            ),
        )

    @property
    def capability(self) -> MathTutorController:
        """Deprecated name retained for read-only legacy callers/tests."""
        return self.controller

    def refresh_model_writer(self) -> None:
        """Rebind the tutor writer after provider credentials change."""
        self.controller.writer = _build_writer(
            self.gateway, self.tutor_preferences.instruction()
        )
        self.controller.chat_responder = TutorChatResponder(
            self.gateway, self.tutor_preferences.instruction()
        )

    async def refresh_embedding_runtime(self) -> None:
        """Resolve the opt-in embedding backend from persisted settings."""
        await self.embedding_config.refresh_runtime()

    @property
    def data_lifecycle(self) -> DataLifecycleService:
        """The ONE application surface for privacy/lifecycle operations
        (Phase 6 round 2, SUBAGENT D module) — dependency-injected from the
        state's existing collaborators, never re-imported from the API layer.

        Lazy + cached: construction is trivial assignment, but the property
        keeps a stable identity for callers (e.g. the desktop privacy panel).
        """
        lifecycle = getattr(self, "_data_lifecycle", None)
        if lifecycle is None:
            from mathtutor.application.data_lifecycle import (
                DataLifecycleService,
            )

            lifecycle = DataLifecycleService(
                documents=self.documents,
                document_repository=self.document_repository,
                storage=self.document_storage,
                memory=self.personal_memory,
                index_manager=self.document_index,
                uow=self.uow,
            )
            self._data_lifecycle = lifecycle
        return lifecycle

    def _relay_wake(self) -> None:
        """Accelerate the resident relay after any committed UoW transaction.

        Best-effort by contract: losing a wake is harmless (the relay loop
        polls every ``idle_seconds``). In-memory mode has no relay — the
        lazy ``getattr`` keeps this a no-op before/without one.
        """
        relay = getattr(self, "outbox_relay", None)
        if relay is not None:
            relay.wake()

    async def admit_request(self) -> bool:
        """Admit one HTTP/WebSocket request unless restore owns the gate."""
        async with self._maintenance_condition:
            if self._maintenance_active:
                return False
            self._active_requests += 1
            return True

    async def release_request(self) -> None:
        async with self._maintenance_condition:
            self._active_requests = max(0, self._active_requests - 1)
            self._maintenance_condition.notify_all()

    async def begin_maintenance(self, *, timeout: float = 5.0) -> bool:
        """Close admission and wait for every request except the caller.

        The restore HTTP request has already been counted by the ASGI gate,
        hence the drain target is one.  Timeout reopens admission and fails
        closed without touching the database.
        """
        async with self._maintenance_condition:
            if self._maintenance_active:
                return False
            self._maintenance_active = True
            try:
                await asyncio.wait_for(
                    self._maintenance_condition.wait_for(
                        lambda: self._active_requests <= 1
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                self._maintenance_active = False
                self._maintenance_condition.notify_all()
                return False
            return True

    async def end_maintenance(self) -> None:
        async with self._maintenance_condition:
            self._maintenance_active = False
            self._maintenance_condition.notify_all()

    async def shutdown_runtime(self) -> None:
        """Stop the resident background runtime (relay loop + backup
        scheduler), then checkpoint the WAL and dispose every engine.
        Graceful and bounded (5s per stop); idempotent.

        Called by the app factory's shutdown event AND first by the backup
        restore orchestration (spec 5.8: the write runtime must be stopped
        and no live connection may hold the database file before it is
        replaced — the checkpoint + dispose here guarantees no active
        ``-wal``/``-shm`` remains).
        """
        import sqlalchemy as sa

        relay = getattr(self, "outbox_relay", None)
        if relay is not None:
            await relay.stop(timeout=5.0)
        scheduler = getattr(self, "backup_scheduler", None)
        if scheduler is not None and scheduler.is_running:
            await scheduler.stop(timeout=5.0)
        worker_shutdown = getattr(self.verification_backend, "shutdown", None)
        if worker_shutdown is not None:
            await worker_shutdown()
        uow = getattr(self, "uow", None)
        checkpoint_complete = False
        if uow is not None:
            try:
                async with uow.engine.connect() as conn:
                    result = await conn.execute(
                        sa.text("PRAGMA wal_checkpoint(TRUNCATE)")
                    )
                    row = result.first()
                    if row is None or int(row[0]) != 0:
                        raise RuntimeError(
                            f"SQLite WAL checkpoint remained busy: {row!r}"
                        )
                    checkpoint_complete = True
            except Exception:
                # Restore must never proceed after a best-effort checkpoint:
                # deleting/replacing the main DB while WAL pages may remain
                # would risk losing committed data.  App shutdown callers also
                # receive the failure instead of a false clean-stop claim.
                await uow.engine.dispose()
                raise
            # ``await dispose()`` (not the sync call) — it actually closes
            # the aiosqlite connections, which is what removes -wal/-shm.
            await uow.engine.dispose()
        store_engine = getattr(self.store, "engine", None)
        if store_engine is not None and store_engine is not uow.engine:
            await store_engine.dispose()
        if checkpoint_complete and self.db_path is not None:
            # SQLite can leave an empty/stale shared-memory sidecar briefly
            # after the final pooled connection closes.  Once checkpoint is
            # confirmed and every owned engine is disposed, WAL/SHM are
            # derived files and may be removed.  Retry briefly to catch a
            # delayed aiosqlite thread close; recreation means an undisposed
            # connection and therefore fails closed.
            sidecars = tuple(
                Path(f"{self.db_path}{suffix}") for suffix in ("-wal", "-shm")
            )
            for _ in range(10):
                for sidecar in sidecars:
                    sidecar.unlink(missing_ok=True)
                await asyncio.sleep(0.02)
                if not any(sidecar.exists() for sidecar in sidecars):
                    break
            else:
                raise RuntimeError(
                    "SQLite WAL/SHM sidecars reappeared after runtime shutdown"
                )

    def _build_context_assembler(self, engine) -> ContextAssembler:
        """Wire the six sources; SQLite-backed education loaders when the
        product database is present, empty-backed in dev/in-memory mode."""
        if engine is not None:
            from mathtutor.repositories import sqlite_education
            from mathtutor.repositories.uow import MathTutorUow

            uow = MathTutorUow(engine)

            async def load_projection(student_id: str):
                async with uow.transaction() as conn:
                    return await sqlite_education.load_student_projection(conn, student_id)

            async def load_observations(student_id: str):
                async with uow.transaction() as conn:
                    return await sqlite_education.load_misconception_observations_for_student(
                        conn, student_id
                    )

            async def load_evidence(student_id: str):
                async with uow.transaction() as conn:
                    return await sqlite_education.load_evidence_for_student(conn, student_id)
        else:
            async def load_projection(student_id: str):
                return None

            async def load_observations(student_id: str):
                return []

            async def load_evidence(student_id: str):
                return []

        return ContextAssembler(
            providers={
                RetrievalSource.STUDENT_MODEL: StudentModelSourceProvider(load_projection),
                RetrievalSource.CURRICULUM: StaticCurriculumProvider(),
                RetrievalSource.MISCONCEPTION_HISTORY: MisconceptionSourceProvider(
                    load_observations
                ),
                RetrievalSource.RECENT_ATTEMPTS: RecentAttemptsSourceProvider(load_evidence),
                RetrievalSource.PERSONAL_MEMORY: PersonalMemorySourceProvider(
                    self.memory_repository
                ),
                RetrievalSource.USER_DOCUMENTS: UserDocumentsSourceProvider(
                    self.document_index
                ),
            }
        )

    def reset(self) -> None:
        """Drop all in-memory sessions (test fixtures / dev reset only).

        SQLite-backed state is reset per-test with a fresh tmp database file
        (see ``reset_product_state``) — never silently wiped here.
        """
        clear_sync = getattr(self.store, "clear_sync", None)
        if clear_sync is None:
            raise RuntimeError(
                "SQLite store cannot be reset synchronously — use a fresh "
                "tmp db path and reset_product_state() in tests"
            )
        clear_sync()


_default_state: ProductState | None = None


def get_product_state(db_path: Path | None = None) -> ProductState:
    """Return the process singleton, initializing it on first use.

    ``db_path`` is honored only on first initialization: pass the same value
    as the app factory (None → in-memory, a path → durable SQLite).
    """
    global _default_state
    if _default_state is None:
        if db_path is not None:
            # Durable mode: BOTH the cycle store and the math-fact
            # repositories live in the same SQLite file — a restart restores
            # cycles AND the verified problems they reference. The knowledge
            # repositories (memory/documents) share that database; imported
            # document bytes live under the SAME data dir (controlled
            # storage: <data_dir>/uploads/<student>/<document>/).
            from mathtutor.infrastructure.db import create_db_engine
            from mathtutor.repositories.sqlite_math_facts import (
                SQLiteProblemRepository,
                SQLiteSolutionRepository,
            )
            from mathtutor.repositories.sqlite_store import SQLiteSessionStore
            from mathtutor.repositories.uow import MathTutorUow

            engine = create_db_engine(db_path)
            uow = MathTutorUow(engine)
            from mathtutor.infrastructure.verifier_worker import (
                VerifierWorkerManager,
            )

            verification_backend = VerifierWorkerManager()
            _default_state = ProductState(
                store=SQLiteSessionStore(engine),
                service=MathTutorApplicationService(
                    problems=SQLiteProblemRepository(uow),
                    solutions=SQLiteSolutionRepository(uow),
                    verification_backend=verification_backend,
                ),
                engine=engine,
                data_dir=db_path.parent,
                db_path=db_path,
                verification_backend=verification_backend,
            )
        else:
            _default_state = ProductState()
    return _default_state


def current_product_state() -> ProductState | None:
    """The process singleton WITHOUT creating it (None before first use).

    The app factory's shutdown hook and the backup-restore orchestration
    use this: they must never SIDE-EFFECT a fresh in-memory state just to
    shut it down.
    """
    return _default_state


def reset_product_state() -> None:
    """Drop the singleton (test fixtures only)."""
    global _default_state
    _default_state = None


__all__ = [
    "BOOT_STEPS",
    "BootstrapTracker",
    "ProductState",
    "current_product_state",
    "get_product_state",
    "reset_product_state",
]

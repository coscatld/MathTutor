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
from mathtutor.infrastructure.observability import MathTutorMetrics
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
        metrics: MathTutorMetrics | None = None,
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
        self.lifecycle_status = "RUNNING"
        self._shutdown_task = None

        # ---- Phase 5/6 knowledge surface -------------------------------
        # The gateway is built FIRST so the capability's writer can be
        # resolved through it (TUTOR_WRITER role; fail-closed template).
        self.secret_store: SecretStore = secret_store or _default_secret_store()
        self.gateway = GenerativeModelGateway(self.secret_store)
        # No embedding backend by default. User settings may replace it only
        # after an explicitly selected local/cloud configuration is ready.
        self.embedding_runtime = embedding_runtime or EmbeddingRuntime()
        # Process-local metric registry. Until now MathTutorMetrics existed but
        # was constructed only by tests, so nothing in production recorded
        # latency/token/release-gate or RAG counters. Retrieval already reports
        # a structured RetrievalExecution per turn; without this instance that
        # report had nowhere to go.
        self.metrics = metrics or MathTutorMetrics()
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
        from mathtutor.repositories.turn_repository import TurnRequestRepository
        self.turn_requests = TurnRequestRepository(engine)
        from mathtutor.repositories.turn_trace_repository import TurnTraceRepository
        self.turn_traces = TurnTraceRepository(engine)
        from mathtutor.repositories.image_repository import ImageRepository
        self.images = ImageRepository(engine)

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
        from mathtutor.infrastructure.cost_policy import CostPolicyService
        self.cost_policy = CostPolicyService(Path(data_dir) / "cost.json")
        from mathtutor.infrastructure.learner_settings import LearnerSettingsService
        self.learner_settings = LearnerSettingsService(Path(data_dir) / "learner.json")

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
        # ONE orchestrator for every initial-retrieval consumer: chat,
        # knowledge QA, hint/explain and practice all go through this object.
        from mathtutor.application.context_expansion import ContextExpander
        from mathtutor.application.retrieval_orchestrator import (
            ConversationRetrievalOrchestrator,
        )

        self.retrieval_orchestrator = ConversationRetrievalOrchestrator(
            kernel=self.document_index,
            expander=ContextExpander(self.document_repository),
            metrics=self.metrics,
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
                self.gateway, self.tutor_preferences.instruction(), learner_settings=self.learner_settings
            ),
        )
        from mathtutor.infrastructure.tutor_intent import SemanticTeachingInterpreter
        self.controller.semantic_interpreter = SemanticTeachingInterpreter(self.gateway)
        self.controller.scene_gateway = self.gateway
        self.controller.learner_settings = self.learner_settings
        self.controller.image_repository = self.images
        from mathtutor.application.chat_documents import ChatDocumentContext
        self.controller.chat_documents = ChatDocumentContext(
            self.documents, self.document_repository,
            self.document_index,
            orchestrator=self.retrieval_orchestrator,
        )
        from mathtutor.learning.knowledge_tracing.package_paths import BUNDLED_PACKAGE
        from mathtutor.learning.knowledge_tracing.service import StudentStateService
        self.student_state = StudentStateService(
            engine, Path(data_dir) / "models" / "dkt" / "model.npz", source_package=BUNDLED_PACKAGE,
        ) if engine is not None else None
        self.store.student_state = self.student_state
        self.store.practice_repository = self.practice_repository
        from mathtutor.application.initial_assessment import InitialAssessmentService
        self.initial_assessment = InitialAssessmentService(engine) if engine is not None else None
        self.adaptive_practice.initial_assessment = self.initial_assessment
        self.adaptive_practice.student_state = self.student_state
        from mathtutor.application.knowledge import KnowledgeService
        from mathtutor.application.knowledge_qa import KnowledgeQA
        self.knowledge = KnowledgeService(self, engine) if engine is not None else None
        self.controller.knowledge = self.knowledge
        self.controller.knowledge_qa = KnowledgeQA(self) if self.knowledge else None
        from mathtutor.application.stage_review import StageReviewService, ReviewDispatchSink
        self.stage_review = StageReviewService(engine, self.student_state) if engine is not None else None
        if self.stage_review:
            self.student_state.stage_review = self.stage_review
            self.outbox_relay.sink = ReviewDispatchSink(self.stage_review, self.outbox_relay.sink)

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
            self.gateway, self.tutor_preferences.instruction(), learner_settings=self.learner_settings
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
            lifecycle.knowledge = self.knowledge
            # D2: deletion must remove the document's conversation bindings
            # too, so the binding table cannot outlive the document it names.
            lifecycle.conversations = self.conversations
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
            if self._maintenance_active or self.lifecycle_status != "RUNNING":
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
            if self._maintenance_active or self.lifecycle_status != "RUNNING":
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
        """Join one owned cleanup task, including when the caller is cancelled."""
        if self.lifecycle_status == "STOPPED":
            return
        if self._shutdown_task is None or self._shutdown_task.done():
            self._shutdown_restore = self._maintenance_active and self.lifecycle_status == "RUNNING"
            self.lifecycle_status = "STOPPING"
            self._maintenance_active = True
            self._shutdown_task = asyncio.create_task(self._shutdown_owned(), name="product-shutdown")
        task = self._shutdown_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancellation of the caller must not abandon connection cleanup.
            await asyncio.shield(task)
            from mathtutor.infrastructure.lifecycle_trace import trace
            trace(id(self), "caller_cancellation_complete")
            raise

    async def _shutdown_owned(self) -> None:
        import sqlalchemy as sa
        from mathtutor.infrastructure.lifecycle_trace import trace

        errors = []
        async def stage(name, action):
            trace(id(self), name + "_begin")
            try:
                await action()
            except BaseException as error:
                errors.append(error)
                trace(id(self), name + "_failed", error=error)
            else:
                trace(id(self), name + "_complete")

        restore = self._shutdown_restore
        self.lifecycle_status = "STOPPING"
        self._maintenance_active = True
        trace(id(self), "shutdown_begin")
        async def drain():
            async with self._maintenance_condition:
                await asyncio.wait_for(self._maintenance_condition.wait_for(
                    lambda: self._active_requests <= (1 if restore else 0)), timeout=5.0)
        await stage("requests", drain)
        for name in ("outbox_relay", "backup_scheduler"):
            service = getattr(self, name, None)
            if service is not None:
                await stage(name, lambda service=service: service.stop(timeout=5.0))
        backup = getattr(self, "backup_service", None)
        if backup is not None:
            await stage("backup_workers", backup.shutdown)
        worker_shutdown = getattr(self.verification_backend, "shutdown", None)
        if worker_shutdown is not None:
            trace(id(self), "owned_verifier",
                  verifier_pid=getattr(getattr(self.verification_backend, "_process", None), "pid", None))
            await stage("verifier", worker_shutdown)
        uow = getattr(self, "uow", None)
        engines = []
        for engine in (getattr(uow, "engine", None), getattr(self.store, "engine", None)):
            if engine is not None and engine not in engines:
                engines.append(engine)
        trace(id(self), "owned_resources", engines=[id(engine) for engine in engines],
              verifier_pid=getattr(getattr(self.verification_backend, "_process", None), "pid", None))
        for engine in engines:
            async def close_engine(engine=engine):
                if getattr(engine.pool, "checkedout", lambda: 0)():
                    raise RuntimeError("Database owners still have checked-out connections")
                # Do not checkpoint while an earlier stage may still own work.
                if not errors:
                    async with engine.connect() as conn:
                        row = (await conn.execute(sa.text("PRAGMA wal_checkpoint(TRUNCATE)"))).first()
                        if row is None or int(row[0]) != 0:
                            raise RuntimeError("SQLite checkpoint still has active owners")
            await stage("checkpoint", close_engine)
            async def dispose(engine=engine):
                if getattr(engine.pool, "checkedout", lambda: 0)():
                    raise RuntimeError("Cannot dispose while sessions still own connections")
                await engine.dispose()
            await stage("dispose", dispose)
        # SQLite owns sidecar deletion. Presence after close is evidence that
        # replacement is unsafe; it is never permission to unlink live files.
        if self.db_path is not None and any(
            Path(f"{self.db_path}{suffix}").exists() for suffix in ("-wal", "-shm")
        ):
            error = RuntimeError("Database owners or sidecars remain after shutdown")
            errors.append(error)
            trace(id(self), "sidecars_remain", error=error)
        if errors:
            self.lifecycle_status = "FAILED"
            self.shutdown_errors = tuple(errors)
            trace(id(self), "shutdown_failed", error=errors[0])
            raise errors[0]
        self.lifecycle_status = "STOPPED"
        trace(id(self), "shutdown_complete")

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
                # F1: the structured path uses the SAME orchestrator as the
                # chat and knowledge paths. The provider is now only a
                # projection from the resulting EvidencePack and holds no
                # retrieval logic of its own.
                RetrievalSource.USER_DOCUMENTS: UserDocumentsSourceProvider(
                    orchestrator=self.retrieval_orchestrator
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

"""MathTutor student product app factory (design doc §13.1, §19).

DEFAULT DENY + EXPLICIT ALLOW: only the MathTutor routers, a minimal auth
subset (login/register/status/profile), and health/version are mounted.
The general DeepTutor app (40+ routers, general ``/ws`` turn runtime,
tool/capability surfaces) is a DIFFERENT trust boundary and is never
imported here.

Startup order (§19):

    load config → validate security gate → create app → routers → start

A P0 security violation raises :class:`SecurityConfigurationError` BEFORE
any router exists — the app refuses to start, it does not warn.
"""

from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from starlette.responses import JSONResponse

from mathtutor.api import auth_router, math_tutor_read, math_tutor_ws
from mathtutor.security.auth import (
    AuthSettings,
    LocalAuthProvider,
    load_auth_settings,
    resolve_auth_data_root,
)
from mathtutor.security.gate import validate_math_tutor_security
from mathtutor.security.settings import (
    MathTutorSecuritySettings,
    load_math_tutor_security_settings,
)

class _MaintenanceGateMiddleware:
    """Drain and reject product traffic while SQLite restore owns the file.

    This is deliberately an ASGI middleware rather than HTTP-only middleware:
    a WebSocket tutoring turn can also hold/use the shared repositories.  The
    restore request itself is admitted first, then closes the ProductState
    gate and waits until it is the sole active request.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        from mathtutor.api.product_state import current_product_state

        state = current_product_state()
        if state is None:
            await self.app(scope, receive, send)
            return
        if not await state.admit_request():
            if scope.get("type") == "websocket":
                await send(
                    {
                        "type": "websocket.close",
                        "code": 1013,
                        "reason": "MathTutor maintenance in progress",
                    }
                )
            else:
                response = JSONResponse(
                    status_code=503,
                    content={"detail": "MathTutor 正在安全恢复数据，请稍后重试。"},
                    headers={"Retry-After": "1"},
                )
                await response(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            await state.release_request()


def create_math_tutor_app(
    settings: MathTutorSecuritySettings | None = None,
    *,
    auth_enabled: bool | None = None,
    auth_secret: str | None = None,
    password_hash: str | None = None,
    db_path: str | None = None,
) -> FastAPI:
    """Create the student-facing MathTutor product app.

    The security gate runs first and raises
    :class:`SecurityConfigurationError` on any P0 violation. Parameters
    allow tests/runners to inject the auth posture; when omitted the real
    DeepTutor runtime settings are read.

    ``db_path`` (Phase 1): None → in-memory store (dev/tests); a path →
    durable SQLite (WAL, CAS, owner isolation). The product state singleton
    is initialized with the same choice.
    """
    settings = settings or load_math_tutor_security_settings()
    auth_data_root = resolve_auth_data_root(db_path)
    loaded_auth = load_auth_settings(auth_data_root)
    effective_auth = AuthSettings(
        enabled=loaded_auth.enabled if auth_enabled is None else auth_enabled,
        secret=loaded_auth.secret if auth_secret is None else auth_secret,
        token_expire_hours=loaded_auth.token_expire_hours,
        cookie_secure=loaded_auth.cookie_secure,
        bootstrap_username=loaded_auth.bootstrap_username,
        bootstrap_password_hash=(
            loaded_auth.bootstrap_password_hash
            if password_hash is None
            else password_hash
        ),
    )

    validate_math_tutor_security(
        settings,
        auth_enabled=effective_auth.enabled,
        auth_secret=effective_auth.secret,
        password_hash=effective_auth.bootstrap_password_hash,
    )

    # Initialize the product runtime BEFORE mounting routers (Phase 1B).
    # With a db path: migrate first (idempotent), then build the durable state.
    from mathtutor.api.product_state import get_product_state, current_product_state, reset_product_state

    previous = current_product_state()
    if previous is not None and previous.lifecycle_status == "STOPPED":
        reset_product_state()

    if db_path is not None:
        from mathtutor.infrastructure.migrate import upgrade_db

        upgrade_db(db_path)
    get_product_state(db_path=None if db_path is None else Path(db_path))

    @asynccontextmanager
    async def lifespan(app):
        async def run_handlers(handlers):
            import inspect
            for handler in handlers:
                result = handler()
                if inspect.isawaitable(result):
                    await result
        try:
            await run_handlers(app.router.on_startup)
        except BaseException:
            try:
                await run_handlers(app.router.on_shutdown)
            except BaseException as cleanup_error:
                from mathtutor.infrastructure.lifecycle_trace import trace
                trace("app", "partial_startup_cleanup_failed", error=cleanup_error)
            raise
        try:
            yield
        finally:
            await run_handlers(app.router.on_shutdown)

    app = FastAPI(
        lifespan=lifespan,
        title="MathTutor Student Product",
        docs_url=None,
        redoc_url=None,
        # OpenAPI stays on: CI scans the route inventory to prove the
        # product app never mounts a general execution surface (§25).
    )
    app.state.math_tutor_auth = LocalAuthProvider(effective_auth, auth_data_root)
    app.add_middleware(_MaintenanceGateMiddleware)

    @app.on_event("startup")
    async def _resolve_embedding_settings() -> None:
        # Cloud credentials are async-resolved from the OS key store. A
        # missing/unavailable key leaves the runtime empty and lexical-ready.
        state = get_product_state(None if db_path is None else Path(db_path))
        await state.refresh_embedding_runtime()

    @app.on_event("startup")
    async def _start_verifier_worker() -> None:
        """Production hard gate: the isolated verifier must be healthy.

        There is deliberately no in-process fallback here.  If the durable
        product profile cannot establish the isolation boundary, startup
        fails before seed publication or student traffic is accepted.
        """
        state = get_product_state(None if db_path is None else Path(db_path))
        start = getattr(state.verification_backend, "start", None)
        if start is not None:
            await start()

    @app.on_event("startup")
    async def _seed_practice_bank() -> None:
        """Phase 5: publish the verified seed exercise bank (idempotent).

        Every seed item runs the FULL release gate (Parser → Solver →
        Verifier → Release Attestation) at startup; repeated calls are
        no-ops (content_hash dedup). A broken seed never blocks serving —
        the failure is logged and practice falls back to template/LLM
        candidates through the same gate.
        """
        try:
            from mathtutor.api.product_state import get_product_state
            state = get_product_state(None if db_path is None else Path(db_path))
            await state.practice_repository.recover_preparing_recommendations()
            if state.student_state is not None:
                from sqlalchemy import select
                from mathtutor.infrastructure.schema import student_profiles
                async with state.uow.transaction() as conn:
                    owners = (await conn.execute(select(student_profiles.c.student_id))).scalars().all()
                    for owner in owners:
                        await state.student_state.import_legacy(owner, conn=conn)
            await state.exercise_release.publish_seed_bank()
        except Exception:  # pragma: no cover - startup resilience
            import logging

            logging.getLogger("math_tutor").warning(
                "seed practice bank failed at startup", exc_info=True
            )

    @app.on_event("startup")
    async def _start_relay_loop() -> None:
        """Phase 6 (round 2): the outbox relay runs as a RESIDENT loop.

        Drains committed events continuously (idle poll every second, wake
        on append via the UoW commit hook). Idempotent + restart-safe by
        construction (the relay ledger keys on the outbox's unique 4-tuple —
        a replay can never dispatch twice). The sink only logs event
        summaries; domain_outbox rows are never mutated. A start failure
        never blocks serving — events accumulate and drain on the next
        successful start.
        """
        try:
            from mathtutor.api.product_state import get_product_state

            relay = get_product_state(
                None if db_path is None else Path(db_path)
            ).outbox_relay
            if relay is not None:
                relay.start()
        except Exception:  # pragma: no cover - startup resilience
            import logging

            logging.getLogger("math_tutor").warning(
                "outbox relay start failed at startup", exc_info=True
            )

    @app.on_event("startup")
    async def _run_bootstrap() -> None:
        """Desktop boot sequence: run the nine-step checks once and record
        them for GET /bootstrap. Runs LAST — the relay above must be started
        before the outbox step probes it. A probe failure is recorded as its
        step status, never raised (the app is already serving)."""
        try:
            from mathtutor.api.desktop_api import run_bootstrap

            await run_bootstrap()
        except Exception:  # pragma: no cover - startup resilience
            import logging

            logging.getLogger("math_tutor").warning(
                "desktop bootstrap probe failed", exc_info=True
            )

    @app.on_event("shutdown")
    async def _stop_runtime() -> None:
        """Stop the resident runtime (relay loop + backup scheduler).

        Uses the singleton WITHOUT creating it — shutdown must never build a
        fresh in-memory state as a side effect. Failures remain observable.
        """
        try:
            from mathtutor.api.product_state import (
                current_product_state,
            )

            state = current_product_state()
            if state is not None:
                await state.shutdown_runtime()
        except Exception:  # pragma: no cover - shutdown resilience
            import logging

            logging.getLogger("math_tutor").warning(
                "runtime shutdown failed", exc_info=True
            )
            raise

    # --- Explicit allowlist (default deny) --------------------------------
    app.include_router(math_tutor_ws.router, prefix="/api/v2/math-tutor")
    app.include_router(math_tutor_read.router, prefix="/api/v2/math-tutor")
    from mathtutor.api.image_api import router as image_router
    app.include_router(image_router)
    # Desktop product bridge (settings/documents/memory/readiness) — a
    # deliberate addition to the student product surface, same auth posture.
    from mathtutor.api import desktop_api
    from mathtutor.api import learning_profile_api
    app.include_router(learning_profile_api.router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX)
    from mathtutor.api.knowledge_api import router as knowledge_router
    app.include_router(knowledge_router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX)

    app.include_router(
        desktop_api.router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX
    )
    app.include_router(auth_router.router, prefix="/api/v2/auth")

    @app.get("/health")
    async def health() -> dict[str, str]:
        payload: dict[str, str] = {"status": "ok", "product": "math_tutor"}
        state = get_product_state(None if db_path is None else Path(db_path))
        worker_health = getattr(state.verification_backend, "health", None)
        if worker_health is None:
            payload["verifier"] = "in_process_dev"
        else:
            try:
                payload["verifier"] = "ok" if await worker_health() else "unavailable"
            except Exception:
                payload["verifier"] = "unavailable"
            if payload["verifier"] != "ok":
                payload["status"] = "degraded"
        if db_path is not None:
            from mathtutor.infrastructure.db import check_db_health

            try:
                payload.update(await check_db_health())
            except Exception as exc:  # readiness must reflect a broken db
                payload["status"] = "degraded"
                payload["db_error"] = str(exc)
        return payload

    @app.get("/version")
    async def version() -> dict[str, object]:
        from mathtutor.release_config import RELEASE_CONFIG

        return {
            "product": "math_tutor",
            "version": RELEASE_CONFIG.app_version,
            "release_config": RELEASE_CONFIG.public_manifest(),
        }

    return app


def create_math_tutor_app_from_runtime() -> FastAPI:
    """Production-style entry: migrate, then build with durable SQLite."""
    from mathtutor.infrastructure.db import resolve_db_path
    from mathtutor.infrastructure.migrate import upgrade_db

    from mathtutor.infrastructure import db_crypto
    db_crypto.apply_pending(resolve_db_path().resolve())  # encryption change chosen by the student
    upgrade_db()  # fail fast before serving (design doc §15 readiness)
    return create_math_tutor_app(
        settings=load_math_tutor_security_settings(),
        db_path=str(resolve_db_path()),
    )


__all__ = [
    "create_math_tutor_app",
    "create_math_tutor_app_from_runtime",
]

"""Product route allowlist: the student app mounts ONLY the allowlisted
routers (Phase 0 §25 — positive allowlist + forbidden-route assertions)."""

from __future__ import annotations

import pytest

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.security.gate import SecurityConfigurationError
from mathtutor.security.settings import MathTutorSecuritySettings
from mathtutor.security.allowlist import MATHTUTOR_FORBIDDEN_ROUTE_MARKERS


def _dev_settings() -> MathTutorSecuritySettings:
    return MathTutorSecuritySettings(environment="development", host="127.0.0.1")


def _app(**overrides) -> object:
    settings = _dev_settings()
    return create_math_tutor_app(settings, auth_enabled=False)


def _flatten_routes(routes: list) -> list:
    """Expand nested router wrappers into concrete route objects.

    Starlette 1.6 wraps included routers in lazy ``_IncludedRouter`` objects
    that materialize via ``effective_candidates()``; this helper flattens
    them so the route-inventory scan sees every real route.
    """
    flat: list = []
    for route in routes:
        if hasattr(route, "effective_candidates"):
            flat.extend(_flatten_routes(list(route.effective_candidates())))
            flat.extend(_flatten_routes(list(route.effective_low_priority_routes())))
        elif hasattr(route, "path"):
            flat.append(route)
        elif hasattr(route, "route"):
            flat.extend(_flatten_routes([route.route]))
        elif hasattr(route, "routes"):
            flat.extend(_flatten_routes(list(route.routes)))
    return flat


def _effective_route(route):
    """Resolve the concrete starlette route behind a route-context wrapper."""
    return getattr(route, "starlette_route", None) or route


def _route_inventory(app) -> list[str]:
    entries: list[str] = []
    for route in _flatten_routes(app.routes):
        concrete = _effective_route(route)
        path = getattr(concrete, "path", "") or ""
        if not path.startswith("/"):
            continue
        # WebSocketRoute has no .methods — it matches the websocket upgrade.
        methods = sorted(getattr(concrete, "methods", None) or getattr(route, "methods", None) or [])
        entries.append(f"{methods} {path}")
    return sorted(entries)


class TestPositiveAllowlist:
    def test_exact_route_inventory(self) -> None:
        # Deliberate Phase 5/Desktop additions on top of the Phase 0 14-route
        # allowlist: GET /offers (practice offers, public projection only)
        # and the /desktop/* bridge (settings/documents/memory/readiness plus
        # the Phase 6 round-2 surfaces: bootstrap/model-test/backups/backup/
        # backup-verify/backup-restore/student-summary).
        # Every entry below is explicit — default deny stays exact.
        app = _app()
        inventory = _route_inventory(app)
        expected = sorted(
            [
                "['GET'] /health",
                "['GET'] /version",
                "['GET'] /api/v2/auth/status",
                "['POST'] /api/v2/auth/login",
                "['POST'] /api/v2/auth/logout",
                "['POST'] /api/v2/auth/register",
                "['GET'] /api/v2/auth/is_first_user",
                "['GET'] /api/v2/auth/profile",
                "['PUT'] /api/v2/auth/profile",
                "['GET'] /api/v2/math-tutor/sessions",
                "['POST'] /api/v2/math-tutor/sessions",
                "['GET'] /api/v2/math-tutor/sessions/{session_id}",
                "['GET'] /api/v2/math-tutor/cycles/{cycle_id}",
                "['GET'] /api/v2/math-tutor/offers",
                "['GET'] /api/v2/math-tutor/desktop/backups",
                "['GET'] /api/v2/math-tutor/desktop/bootstrap",
                "['DELETE'] /api/v2/math-tutor/desktop/documents/{document_id}",
                "['DELETE'] /api/v2/math-tutor/desktop/memory/{memory_id}",
                "['GET'] /api/v2/math-tutor/desktop/documents",
                "['GET'] /api/v2/math-tutor/desktop/documents/{document_id}",
                "['GET'] /api/v2/math-tutor/desktop/memory",
                "['GET'] /api/v2/math-tutor/desktop/privacy/export",
                "['GET'] /api/v2/math-tutor/desktop/readiness",
                "['GET'] /api/v2/math-tutor/desktop/settings",
                "['GET'] /api/v2/math-tutor/desktop/settings/embedding",
                "['GET'] /api/v2/math-tutor/desktop/settings/models",
                "['GET'] /api/v2/math-tutor/desktop/settings/presets",
                "['GET'] /api/v2/math-tutor/desktop/settings/tutor",
                "['DELETE'] /api/v2/math-tutor/desktop/settings/api-key",
                "['DELETE'] /api/v2/math-tutor/desktop/settings/embedding/api-key",
                "['DELETE'] /api/v2/math-tutor/desktop/settings/embedding/local/{model_id}",
                "['GET'] /api/v2/math-tutor/desktop/student-summary",
                "['PATCH'] /api/v2/math-tutor/desktop/documents/{document_id}/retrieval",
                "['PATCH'] /api/v2/math-tutor/desktop/documents/{document_id}",
                "['PATCH'] /api/v2/math-tutor/desktop/memory/{memory_id}/retrieval",
                "['POST'] /api/v2/math-tutor/desktop/backup",
                "['POST'] /api/v2/math-tutor/desktop/backup/restore",
                "['POST'] /api/v2/math-tutor/desktop/backup/verify",
                "['POST'] /api/v2/math-tutor/desktop/documents/import",
                "['POST'] /api/v2/math-tutor/desktop/documents/pick",
                "['POST'] /api/v2/math-tutor/desktop/conversations/{conversation_id}/documents/{document_id}",
                "['DELETE'] /api/v2/math-tutor/desktop/conversations/{conversation_id}/documents/{document_id}",
                "['POST'] /api/v2/math-tutor/desktop/memory",
                "['POST'] /api/v2/math-tutor/desktop/memory/{memory_id}/confirm",
                "['POST'] /api/v2/math-tutor/desktop/model/test",
                "['POST'] /api/v2/math-tutor/desktop/privacy/educational-history",
                "['POST'] /api/v2/math-tutor/desktop/privacy/purge-documents",
                "['POST'] /api/v2/math-tutor/desktop/privacy/purge-memory",
                "['POST'] /api/v2/math-tutor/desktop/privacy/rebuild-indexes",
                "['POST'] /api/v2/math-tutor/desktop/settings/test-connection",
                "['POST'] /api/v2/math-tutor/desktop/settings/embedding/local/download",
                "['POST'] /api/v2/math-tutor/desktop/settings/embedding/test",
                "['POST'] /api/v2/math-tutor/desktop/settings/onboarding/skip",
                "['PUT'] /api/v2/math-tutor/desktop/documents/{document_id}",
                "['PUT'] /api/v2/math-tutor/desktop/memory/{memory_id}",
                "['PUT'] /api/v2/math-tutor/desktop/settings",
                "['PUT'] /api/v2/math-tutor/desktop/settings/embedding",
                "['PUT'] /api/v2/math-tutor/desktop/settings/tutor",
                "[] /api/v2/math-tutor/ws",  # WebSocketRoute (upgrade, no HTTP methods)
                "['GET', 'HEAD'] /openapi.json",
            ]
        )
        assert inventory == expected, f"route drift:\n{inventory}"

    def test_websocket_entry_exists(self) -> None:
        app = _app()
        paths = [_effective_route(route).path for route in _flatten_routes(app.routes)]
        assert "/api/v2/math-tutor/ws" in paths

    def test_openapi_inventory_exposed_for_ci(self) -> None:
        app = _app()
        schema = app.openapi()
        assert "/api/v2/math-tutor/ws" not in schema["paths"]  # WS not in REST openapi
        assert "/api/v2/math-tutor/sessions" in schema["paths"]


class TestForbiddenRoutes:
    def test_no_forbidden_route_markers(self) -> None:
        app = _app()
        inventory = " ".join(_route_inventory(app)).lower()
        for marker in MATHTUTOR_FORBIDDEN_ROUTE_MARKERS:
            assert marker not in inventory, f"forbidden route marker {marker!r} found"

    def test_general_deeptutor_routes_absent(self) -> None:
        app = _app()
        paths = {_effective_route(route).path for route in _flatten_routes(app.routes)}
        for forbidden_path in (
            "/api/v1/chat",
            "/api/v1/ws",  # general turn runtime WebSocket
            "/api/v1/tools",
            "/api/v1/subagents",
            "/api/v1/plugins",
            "/api/v1/space/mcp",
            "/api/v1/knowledge",
            "/api/v1/book",
            "/api/v1/notebook",
            "/api/v1/question",
            "/api/v1/partners",
            "/api/v1/co-writer",
            "/api/v1/voice",
            "/api/v1/mastery",
            "/api/v1/skills",
            "/api/v1/space/cli-apps",
            "/api/v1/auth/users",  # admin user management
            "/api/v1/auth/openai-codex/callback",
        ):
            assert forbidden_path not in paths


class TestStartupGateInsideFactory:
    def test_production_insecure_factory_refuses(self) -> None:
        settings = MathTutorSecuritySettings(environment="production")
        with pytest.raises(SecurityConfigurationError):
            create_math_tutor_app(settings, auth_enabled=False)

    def test_development_non_loopback_refuses(self) -> None:
        settings = MathTutorSecuritySettings(environment="development", host="0.0.0.0")
        with pytest.raises(SecurityConfigurationError):
            create_math_tutor_app(settings, auth_enabled=False)

    def test_production_secure_factory_creates_app(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = MathTutorSecuritySettings(environment="production")
        app = create_math_tutor_app(
            settings,
            auth_enabled=True,
            auth_secret="x" * 64,
            password_hash="",
        )
        assert app.title == "MathTutor Student Product"

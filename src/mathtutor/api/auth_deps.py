"""Standalone HTTP/WS authentication and owner-scope dependencies."""

from __future__ import annotations

from fastapi import Cookie, Header, HTTPException, Request, WebSocket, status

from mathtutor.security.auth import AuthProvider
from mathtutor.security.scopes import (
    PrincipalScope,
    StudentOwnerScope,
    dev_student_owner,
)
from mathtutor.security.settings import load_math_tutor_security_settings

_COOKIE_NAME = "dt_token"


def _provider(connection: Request | WebSocket) -> AuthProvider:
    provider = getattr(connection.app.state, "math_tutor_auth", None)
    if provider is None:
        raise RuntimeError("MathTutor AuthProvider is not installed")
    return provider


def _extract_token(authorization: str | None, cookie: str | None) -> str | None:
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip() or None
    return cookie


def _dev_owner_or_fail() -> StudentOwnerScope:
    settings = load_math_tutor_security_settings()
    if (
        settings.environment in {"development", "test"}
        and settings.allow_loopback_without_auth
        and settings.is_loopback()
    ):
        return dev_student_owner(settings)
    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_principal(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> PrincipalScope | None:
    provider = _provider(request)
    if not provider.settings.enabled:
        return None
    token = _extract_token(authorization, dt_token)
    principal = provider.decode_token(token) if token else None
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


async def require_student_owner(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> StudentOwnerScope:
    principal = await require_principal(request, authorization, dt_token)
    if principal is None:
        return _dev_owner_or_fail()
    return StudentOwnerScope(principal=principal, student_id=principal.user_id)


async def ws_require_student_owner(ws: WebSocket) -> StudentOwnerScope | None:
    """Authenticate before ``accept``; invalid upgrades close with 4001."""
    provider = _provider(ws)
    if not provider.settings.enabled:
        try:
            return _dev_owner_or_fail()
        except HTTPException:
            await ws.close(code=4001)
            return None
    token = ws.query_params.get("token") or ws.cookies.get(_COOKIE_NAME)
    principal = provider.decode_token(token) if token else None
    if principal is None:
        await ws.close(code=4001)
        return None
    return StudentOwnerScope(principal=principal, student_id=principal.user_id)


__all__ = ["require_principal", "require_student_owner", "ws_require_student_owner"]

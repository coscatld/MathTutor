"""The six allowlisted standalone MathTutor auth routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from starlette.responses import JSONResponse

from mathtutor.api.auth_deps import require_principal
from mathtutor.security.auth import AuthProvider
from mathtutor.security.auth_store import AuthStoreError, AuthStoreBusy
from mathtutor.security.auth_runtime import AuthExecutor, AuthAttemptBudget, AuthBusy, AuthRateLimited
from mathtutor.security.scopes import PrincipalScope

router = APIRouter()
_COOKIE_NAME = "dt_token"
_ICON_MARKER_RE = re.compile(r"^icon:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}$")


def _provider(request: Request) -> AuthProvider:
    return request.app.state.math_tutor_auth


def install_auth_runtime(app) -> None:
    app.state.math_tutor_auth_executor = AuthExecutor()
    app.state.math_tutor_auth_attempts = AuthAttemptBudget()

    async def unavailable(request, error):
        recovery = isinstance(error, AuthStoreError)
        limited = isinstance(error, AuthRateLimited)
        return JSONResponse({
            "code": "auth_storage_recovery_required" if recovery else "auth_rate_limited" if limited else "auth_busy",
            "detail": "Account storage needs recovery; registration is closed." if recovery else str(error),
            "enabled": True, "authenticated": False, "is_first_user": False,
            "recovery_required": recovery,
        }, status_code=503 if recovery or not limited else 429,
            headers={} if recovery else {"Retry-After": "60" if limited else "1"})

    for error in (AuthStoreError, AuthStoreBusy, AuthBusy, AuthRateLimited):
        app.add_exception_handler(error, unavailable)

    @app.on_event("shutdown")
    async def stop_auth_workers():
        await app.state.math_tutor_auth_executor.shutdown()


async def _run(request, function, *args):
    return await request.app.state.math_tutor_auth_executor.run(function, *args)


def _admit_attempt(request):
    # Never use raw forwarding headers as the limiter's identity.
    peer = request.client.host if request.client else "unknown"
    request.app.state.math_tutor_auth_attempts.admit(peer)


class LoginRequest(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=128)

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        return value


class UpdateProfileRequest(BaseModel):
    avatar: str

    @field_validator("avatar")
    @classmethod
    def valid_avatar(cls, value: str) -> str:
        value = value.strip()
        if value and not _ICON_MARKER_RE.fullmatch(value):
            raise ValueError("Avatar must be empty or 'icon:<name>:<color>'")
        return value


def _cookie_attrs(provider: AuthProvider) -> dict:
    secure = provider.settings.cookie_secure
    return {
        "key": _COOKIE_NAME,
        "httponly": True,
        "samesite": "none" if secure else "lax",
        "secure": secure,
    }


@router.get("/status")
async def auth_status(request: Request) -> dict:
    provider = _provider(request)
    if not provider.settings.enabled:
        principal = provider.local_principal()
        return {
            "enabled": False,
            "authenticated": True,
            "user_id": principal.user_id,
            "username": principal.username,
            "role": principal.role,
            "is_admin": principal.role == "admin",
            "avatar": "",
        }
    authorization = request.headers.get("authorization")
    token = request.cookies.get(_COOKIE_NAME)
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    principal = provider.decode_token(token) if token else None
    first = await _run(request, provider.is_first_user)
    profile = await _run(request, provider.profile, principal.username) if principal else None
    return {
        "enabled": True,
        "authenticated": principal is not None,
        "user_id": principal.user_id if principal else None,
        "username": principal.username if principal else None,
        "role": principal.role if principal else None,
        "is_admin": principal.role == "admin" if principal else False,
        "avatar": str((profile or {}).get("avatar") or ""),
        "is_first_user": first,
        "recovery_required": False,
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict:
    provider = _provider(request)
    if not provider.settings.enabled:
        return {"ok": True, "message": "Auth is disabled — no login required."}
    _admit_attempt(request)
    principal = await _run(request, provider.authenticate, body.username, body.password)
    if principal is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = provider.create_token(principal)
    response.set_cookie(
        value=token,
        max_age=provider.settings.token_expire_hours * 3600,
        **_cookie_attrs(provider),
    )
    return {
        "ok": True,
        "user_id": principal.user_id,
        "username": principal.username,
        "role": principal.role,
        "is_admin": principal.role == "admin",
    }


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    response.delete_cookie(**_cookie_attrs(_provider(request)))
    return {"ok": True}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request) -> dict:
    provider = _provider(request)
    if not provider.settings.enabled:
        raise HTTPException(status_code=400, detail="Auth is disabled — registration is not available.")
    _admit_attempt(request)
    try:
        principal = await _run(request, provider.register_first_user, body.username, body.password)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "user_id": principal.user_id,
        "username": principal.username,
        "role": principal.role,
        "is_first_user": True,
        "is_admin": principal.role == "admin",
    }


@router.get("/is_first_user")
async def is_first_user(request: Request) -> dict:
    provider = _provider(request)
    return {
        "is_first_user": await _run(request, provider.is_first_user) if provider.settings.enabled else False
    }


@router.get("/profile")
async def get_profile(
    request: Request,
    principal: PrincipalScope | None = Depends(require_principal),
) -> dict:
    if principal is None:
        raise HTTPException(status_code=400, detail="Auth is disabled — profiles are not available.")
    profile = await _run(request, _provider(request).profile, principal.username)
    return profile or {
        "id": principal.user_id,
        "username": principal.username,
        "role": principal.role,
        "created_at": "",
        "disabled": False,
        "avatar": "",
    }


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    principal: PrincipalScope | None = Depends(require_principal),
) -> dict:
    if principal is None:
        raise HTTPException(status_code=400, detail="Auth is disabled — profiles are not available.")
    if not await _run(request, _provider(request).set_avatar, principal.username, body.avatar):
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "avatar": body.avatar}


__all__ = ["router"]

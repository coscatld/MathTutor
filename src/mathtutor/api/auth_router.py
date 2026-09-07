"""The six allowlisted standalone MathTutor auth routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator

from mathtutor.api.auth_deps import require_principal
from mathtutor.security.auth import AuthProvider
from mathtutor.security.scopes import PrincipalScope

router = APIRouter()
_COOKIE_NAME = "dt_token"
_ICON_MARKER_RE = re.compile(r"^icon:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}$")


def _provider(request: Request) -> AuthProvider:
    return request.app.state.math_tutor_auth


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str

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
    profile = provider.profile(principal.username) if principal else None
    return {
        "enabled": True,
        "authenticated": principal is not None,
        "user_id": principal.user_id if principal else None,
        "username": principal.username if principal else None,
        "role": principal.role if principal else None,
        "is_admin": principal.role == "admin" if principal else False,
        "avatar": str((profile or {}).get("avatar") or ""),
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict:
    provider = _provider(request)
    if not provider.settings.enabled:
        return {"ok": True, "message": "Auth is disabled — no login required."}
    principal = provider.authenticate(body.username, body.password)
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
    try:
        principal = provider.register_first_user(body.username, body.password)
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
        "is_first_user": provider.is_first_user() if provider.settings.enabled else False
    }


@router.get("/profile")
async def get_profile(
    request: Request,
    principal: PrincipalScope | None = Depends(require_principal),
) -> dict:
    if principal is None:
        raise HTTPException(status_code=400, detail="Auth is disabled — profiles are not available.")
    profile = _provider(request).profile(principal.username)
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
    if not _provider(request).set_avatar(principal.username, body.avatar):
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "avatar": body.avatar}


__all__ = ["router"]

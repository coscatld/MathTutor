"""Minimal standalone authentication for the MathTutor product boundary."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from mathtutor.security.scopes import PrincipalScope


@dataclass(frozen=True, slots=True)
class AuthSettings:
    enabled: bool = False
    secret: str = ""
    token_expire_hours: int = 24
    cookie_secure: bool = False
    bootstrap_username: str = ""
    bootstrap_password_hash: str = ""


class AuthProvider(Protocol):
    settings: AuthSettings

    def decode_token(self, token: str) -> PrincipalScope | None: ...
    def create_token(self, principal: PrincipalScope) -> str: ...
    def authenticate(self, username: str, password: str) -> PrincipalScope | None: ...
    def register_first_user(self, username: str, password: str) -> PrincipalScope: ...
    def is_first_user(self) -> bool: ...
    def profile(self, username: str) -> dict | None: ...
    def set_avatar(self, username: str, avatar: str) -> bool: ...


def resolve_auth_data_root(db_path: str | None = None) -> Path:
    explicit = os.environ.get("MATHTUTOR_DATA_ROOT", "").strip()
    if explicit:
        return Path(explicit).resolve()
    if db_path:
        return Path(db_path).resolve().parent
    legacy_home = os.environ.get("DEEPTUTOR_HOME", "").strip()
    if legacy_home:
        return (Path(legacy_home) / "data").resolve()
    return (Path.cwd() / "data").resolve()


def load_auth_settings(data_root: Path | None = None) -> AuthSettings:
    """Load only MathTutor auth settings; no generic settings package."""
    root = (data_root or resolve_auth_data_root()).resolve()
    settings_path = root / "user" / "settings" / "auth.json"
    raw: dict = {}
    try:
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    except (OSError, ValueError):
        pass
    # The standalone name wins. AUTH_* and DEEPTUTOR_* remain deprecated,
    # read-only aliases for one upgrade cycle; new child processes emit only
    # MATHTUTOR_*.
    enabled_env = (
        os.environ.get("MATHTUTOR_AUTH_ENABLED")
        or os.environ.get("AUTH_ENABLED")
        or os.environ.get("DEEPTUTOR_AUTH_ENABLED")
    )
    enabled = (
        enabled_env.strip().lower() in {"1", "true", "yes", "on"}
        if enabled_env is not None
        else bool(raw.get("enabled", False))
    )
    secret = (
        os.environ.get("MATHTUTOR_AUTH_SECRET")
        or os.environ.get("AUTH_SECRET")
        or os.environ.get("DEEPTUTOR_AUTH_SECRET")
        or ""
    ).strip()
    if enabled and not secret:
        secret_path = root / "user" / "auth_secret"
        try:
            secret = secret_path.read_text(encoding="utf-8").strip()
        except OSError:
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret = secrets.token_urlsafe(48)
            secret_path.write_text(secret, encoding="utf-8")
            try:
                secret_path.chmod(0o600)
            except OSError:
                pass
    return AuthSettings(
        enabled=enabled,
        secret=secret,
        token_expire_hours=int(raw.get("token_expire_hours") or 24),
        cookie_secure=bool(raw.get("cookie_secure", False)),
        bootstrap_username=str(raw.get("username") or ""),
        bootstrap_password_hash=str(raw.get("password_hash") or ""),
    )


class LocalAuthProvider:
    """bcrypt + HS256 + local JSON user store, scoped to MathTutor data root."""

    def __init__(self, settings: AuthSettings, data_root: Path) -> None:
        self.settings = settings
        self._store_path = data_root.resolve() / "user" / "auth_users.json"

    def _load_users(self) -> dict[str, dict]:
        try:
            loaded = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        users = loaded if isinstance(loaded, dict) else {}
        if not users and self.settings.bootstrap_username and self.settings.bootstrap_password_hash:
            users[self.settings.bootstrap_username] = {
                "id": "env-admin",
                "hash": self.settings.bootstrap_password_hash,
                "role": "admin",
                "created_at": "",
                "disabled": False,
                "avatar": "",
            }
        return users

    def _save_users(self, users: dict[str, dict]) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._store_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(users, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(self._store_path)

    def is_first_user(self) -> bool:
        return not self._load_users()

    def register_first_user(self, username: str, password: str) -> PrincipalScope:
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,128}", username):
            raise ValueError("Enter a valid username or email address")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        users = self._load_users()
        if users:
            raise PermissionError("Self-registration is closed")
        import bcrypt

        user_id = f"u_{uuid4().hex}"
        users[username] = {
            "id": user_id,
            "hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "disabled": False,
            "avatar": "",
        }
        self._save_users(users)
        return PrincipalScope(user_id=user_id, username=username, role="admin")

    def authenticate(self, username: str, password: str) -> PrincipalScope | None:
        record = self._load_users().get(username)
        if not record or record.get("disabled"):
            return None
        import bcrypt

        try:
            valid = bcrypt.checkpw(password.encode(), str(record.get("hash") or "").encode())
        except Exception:
            valid = False
        if not valid:
            return None
        return PrincipalScope(
            user_id=str(record.get("id") or ""),
            username=username,
            role=str(record.get("role") or "user"),
        )

    def create_token(self, principal: PrincipalScope) -> str:
        from jose import jwt

        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": principal.username,
                "role": principal.role,
                "uid": principal.user_id,
                "iat": now,
                "exp": now + timedelta(hours=self.settings.token_expire_hours),
            },
            self.settings.secret,
            algorithm="HS256",
        )

    def decode_token(self, token: str) -> PrincipalScope | None:
        from jose import JWTError, jwt

        try:
            payload = jwt.decode(token, self.settings.secret, algorithms=["HS256"])
            username = str(payload.get("sub") or "")
            user_id = str(payload.get("uid") or "")
            if not username or not user_id:
                return None
            return PrincipalScope(
                user_id=user_id,
                username=username,
                role=str(payload.get("role") or "user"),
            )
        except JWTError:
            return None

    def profile(self, username: str) -> dict | None:
        record = self._load_users().get(username)
        if record is None:
            return None
        return {
            "id": str(record.get("id") or ""),
            "username": username,
            "role": str(record.get("role") or "user"),
            "created_at": str(record.get("created_at") or ""),
            "disabled": bool(record.get("disabled", False)),
            "avatar": str(record.get("avatar") or ""),
        }

    def set_avatar(self, username: str, avatar: str) -> bool:
        users = self._load_users()
        if username not in users:
            return False
        users[username]["avatar"] = avatar
        self._save_users(users)
        return True


__all__ = [
    "AuthProvider",
    "AuthSettings",
    "LocalAuthProvider",
    "load_auth_settings",
    "resolve_auth_data_root",
]

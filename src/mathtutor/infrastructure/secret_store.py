"""SecretStore — where generative API keys live. NEVER the business DB.

Design requirement: a generative API key may not be stored in source
code, git, ordinary config JSON, or a plain SQLite business table. The
business layer only ever receives a *credential reference* (secret key
name); the secret itself is resolved through the store at call time.

Desktop production backs this Protocol with the operating-system credential
store (macOS Keychain / Windows Credential Manager / freedesktop Secret
Service). The in-memory implementation remains limited to development and
tests; callers never branch on the operating system.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class SecretStore(Protocol):
    """Async secret key-value store (keys are names, values are secrets)."""

    async def put(self, key: str, value: str) -> None: ...

    async def get(self, key: str) -> str | None: ...

    async def delete(self, key: str) -> None: ...


class SecretRef(BaseModel):
    """Credential reference handed to business code (no secret material)."""

    model_config = ConfigDict(frozen=True)

    store_id: str
    key: str


class SecretStoreUnavailableError(RuntimeError):
    """Raised when a required secret is missing from the store."""


class InMemorySecretStore:
    """Process-local store (dev/tests). Values never touch disk or DB."""

    store_id = "memory"

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    async def put(self, key: str, value: str) -> None:
        self._secrets[key] = value

    async def get(self, key: str) -> str | None:
        return self._secrets.get(key)

    async def delete(self, key: str) -> None:
        self._secrets.pop(key, None)

    def clear_sync(self) -> None:
        """Sync convenience for test fixtures."""
        self._secrets.clear()


__all__ = [
    "InMemorySecretStore",
    "SecretRef",
    "SecretStore",
    "SecretStoreUnavailableError",
]

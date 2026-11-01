"""Fail-closed account storage; initialization is durable, never inferred from {}."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import re
import tempfile

from mathtutor.infrastructure.migration_lock import migration_lock


class AuthStoreError(RuntimeError):
    """Preserve damaged account bytes and require operator recovery."""


class AuthStoreBusy(RuntimeError):
    """Another process is performing an account transaction."""


_MAX_STORE_BYTES = 256 * 1024
_USERNAME = re.compile(r"[A-Za-z0-9_.@-]{3,128}\Z")
_IDENTITY = re.compile(r"[A-Za-z0-9_.:@-]{1,128}\Z")
# Never silently lower/re-hash existing credentials. Costs above this
# admission ceiling require deliberate operator recovery before login.
MAX_BCRYPT_COST = 16
_BCRYPT = re.compile(r"\$2[aby]\$(?:0[4-9]|1[0-6])\$[./A-Za-z0-9]{53}\Z")
_MARKER = {"schema_version": 1, "initialized": True}
MISSING = object()


def atomic_bytes(path: Path, value: bytes) -> None:
    """Unique sibling file, mode 0600, then durable atomic publication."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError as exc:
        raise AuthStoreError("Account storage needs recovery") from exc
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def atomic_json(path: Path, value: dict) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


class AuthStore:
    def __init__(self, root: Path):
        self.path = root.resolve() / "user" / "auth_users.json"
        self.marker = self.path.with_name("auth_initialized.json")

    @contextmanager
    def transaction(self):
        # Reuse the existing OS lock implementation; its distinct account
        # path cannot contend with the database migration lock. Never unlink.
        with ExitStack() as stack:
            try:
                stack.enter_context(migration_lock(self.path, timeout=1.0))
            except TimeoutError as exc:
                raise AuthStoreBusy("Account storage is busy; retry shortly") from exc
            except OSError as exc:
                raise AuthStoreError("Account storage needs recovery") from exc
            yield

    @staticmethod
    def _read(path: Path):
        try:
            with path.open("rb") as stream:
                data = stream.read(_MAX_STORE_BYTES + 1)
        except FileNotFoundError:
            # A dangling symlink is an existing broken store, not a fresh one.
            if path.is_symlink():
                raise AuthStoreError("Account storage needs recovery")
            return MISSING
        except OSError as exc:
            raise AuthStoreError("Account storage needs recovery") from exc
        try:
            if len(data) > _MAX_STORE_BYTES:
                raise ValueError("oversized store")
            def object_value(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("duplicate object key")
                    value[key] = item
                return value
            return json.loads(data, object_pairs_hook=object_value)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise AuthStoreError("Account storage needs recovery") from exc

    @staticmethod
    def validate(users):
        if not isinstance(users, dict) or not users:
            raise AuthStoreError("Account storage needs recovery")
        identities = set()
        for username, record in users.items():
            if not isinstance(username, str) or not _USERNAME.fullmatch(username) or not isinstance(record, dict):
                raise AuthStoreError("Account storage needs recovery")
            identity = record.get("id")
            if (not isinstance(identity, str) or not _IDENTITY.fullmatch(identity) or identity in identities
                    or not isinstance(record.get("hash"), str) or not _BCRYPT.fullmatch(record["hash"])
                    or record.get("role") not in {"admin", "user"}
                    or not isinstance(record.get("disabled", False), bool)
                    or not isinstance(record.get("created_at", ""), str)
                    or not isinstance(record.get("avatar", ""), str)):
                raise AuthStoreError("Account storage needs recovery")
            identities.add(identity)
        return users

    def load(self, *, bootstrap_username="", bootstrap_password_hash="") -> dict:
        """Must be called while holding transaction; migrate only valid records."""
        marker = self._read(self.marker)
        if marker is not MISSING and marker != _MARKER:
            raise AuthStoreError("Account storage needs recovery")
        loaded = self._read(self.path)
        if loaded is not MISSING:
            users = self.validate(loaded)
            if marker is MISSING:
                # Legacy owner IDs are retained verbatim; no account rewrite.
                atomic_json(self.marker, _MARKER)
            return users
        if marker is not MISSING:
            raise AuthStoreError("Account storage needs recovery")
        if bootstrap_username or bootstrap_password_hash:
            users = self.validate({bootstrap_username: {
                "id": "env-admin", "hash": bootstrap_password_hash, "role": "admin",
                "created_at": "", "disabled": False, "avatar": "",
            }})
            self.save(users)
            return users
        return {}

    def save(self, users: dict) -> None:
        self.validate(users)
        try:
            serialized = (json.dumps(users, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
            raise AuthStoreError("Account storage needs recovery") from exc
        if len(serialized) > _MAX_STORE_BYTES:
            raise AuthStoreError("Account storage needs recovery")
        # Publishing the marker first means interrupted initialization fails
        # closed. Recovery restores the original accounts, never new owners.
        atomic_json(self.marker, _MARKER)
        atomic_bytes(self.path, serialized)

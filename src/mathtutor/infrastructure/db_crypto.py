"""Encryption at rest with SQLCipher: opt-in for the database, always for backups.

The product database stays plaintext unless the student turns encryption on.
Turning it on (or off) only records a pending change; the conversion runs at
the next start, before anything opens the database:

    verify source -> export into a temporary file in the target mode ->
    integrity_check + identical row counts -> atomic swap -> marker updated

Any failure leaves the original file untouched and the marker unchanged.

Backups are SQLCipher files keyed by a separate backup key whenever a
persistent key store exists, so a copied backup is unreadable without it.
The backup key can be shown to the student as a recovery key; restore
accepts it when the key store entry is gone. Plaintext backups from older
versions remain restorable.

Keys live only in the OS credential store (Keychain / Credential Manager).
An in-memory store is never used for real data: losing it on restart would
lock the student out. Tests inject their own store with ``use_keystore``.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

MARKER_SUFFIX = ".encryption.json"
DB_KEY_NAME = "db-encryption-key-v1"
BACKUP_KEY_NAME = "backup-encryption-key-v1"
_SQLITE_HEADER = b"SQLite format 3\x00"

_keystore = None
_keystore_lock = threading.Lock()


class EncryptionUnavailable(RuntimeError):
    """SQLCipher or a persistent key store is missing."""


def sqlcipher_available() -> bool:
    try:
        import sqlcipher3  # noqa: F401
    except ImportError:
        return False
    return True


def use_keystore(store) -> None:
    """Install the key store (tests use an in-memory one)."""
    global _keystore
    with _keystore_lock:
        _keystore = store


def _store():
    global _keystore
    with _keystore_lock:
        if _keystore is None:
            from mathtutor.infrastructure.keychain_secret_store import KeychainSecretStore
            _keystore = KeychainSecretStore() if KeychainSecretStore.available() else False
        return _keystore or None


def _run(coro):
    """Run a key-store coroutine from sync or async callers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict[str, Any] = {}

    def worker():
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            result["error"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def available() -> bool:
    return sqlcipher_available() and _store() is not None


def get_key(name: str) -> str | None:
    store = _store()
    return None if store is None else _run(store.get(name))


def ensure_key(name: str) -> str:
    store = _store()
    if store is None:
        raise EncryptionUnavailable("没有可用的系统密钥存储")
    key = _run(store.get(name))
    if not key:
        key = secrets.token_hex(32)
        _run(store.put(name, key))
        if _run(store.get(name)) != key:
            raise EncryptionUnavailable("密钥写入系统凭据存储后无法读回")
    return key


# ------------------------------------------------------------------ marker

def marker_path(db_path: Path) -> Path:
    return Path(f"{db_path}{MARKER_SUFFIX}")


def state(db_path: Path) -> dict:
    path = marker_path(db_path)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("mode") in {"plaintext", "encrypted"}:
                return {"mode": data["mode"], "pending": data.get("pending")}
        except (OSError, ValueError):
            pass
    return {"mode": "plaintext", "pending": None}


def _write_state(db_path: Path, mode: str, pending: str | None) -> None:
    path = marker_path(db_path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"mode": mode, "pending": pending}) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def request_change(db_path: Path, enabled: bool) -> dict:
    """Record the wanted mode; the conversion runs at the next start."""
    current = state(db_path)
    wanted = "encrypted" if enabled else "plaintext"
    if enabled:
        if not available():
            raise EncryptionUnavailable("当前环境缺少 SQLCipher 或系统密钥存储，无法加密")
        ensure_key(DB_KEY_NAME)
    pending = None if wanted == current["mode"] else ("encrypt" if enabled else "decrypt")
    _write_state(db_path, current["mode"], pending)
    return state(db_path)


# ------------------------------------------------------------- connections

def is_plaintext_file(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(16) == _SQLITE_HEADER
    except OSError:
        return False


def connect(path: Path | str, *, key: str | None = None, readonly: bool = False, **kwargs):
    """DB-API connection: SQLCipher with ``key``, stdlib sqlite3 without."""
    target = f"file:{path}?mode=ro" if readonly else str(path)
    if key is None:
        return sqlite3.connect(target, uri=readonly, **kwargs)
    import sqlcipher3
    connection = sqlcipher3.connect(target, uri=readonly, **kwargs)
    connection.execute(f"PRAGMA key = \"x'{key}'\"")
    return connection


def db_key(db_path: Path) -> str | None:
    """The key the live database needs, or None for plaintext."""
    if state(db_path)["mode"] != "encrypted":
        return None
    key = get_key(DB_KEY_NAME)
    if not key:
        raise EncryptionUnavailable("数据库已加密，但系统凭据存储中找不到密钥")
    return key


def connect_db(db_path: Path | str, **kwargs):
    return connect(db_path, key=db_key(Path(db_path)), **kwargs)


def key_for_file(path: Path, *, recovery_key: str | None = None) -> str | None:
    """Plaintext → None; otherwise the first key that opens it."""
    if is_plaintext_file(path):
        return None
    for candidate in (recovery_key, get_key(BACKUP_KEY_NAME), get_key(DB_KEY_NAME)):
        if candidate and integrity(path, candidate) == "ok":
            return candidate
    raise EncryptionUnavailable("备份已加密，需要恢复密钥才能打开")


def integrity(path: Path, key: str | None) -> str:
    try:
        with closing(connect(path, key=key)) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return str(row[0]) if row else "missing"
    except Exception as exc:  # noqa: BLE001 - any open failure is not ok
        return f"unreadable: {type(exc).__name__}"


def row_counts(path: Path, key: str | None) -> dict[str, int]:
    with closing(connect(path, key=key)) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def export(source: Path, source_key: str | None, target: Path, target_key: str | None) -> None:
    """Copy every table into ``target`` encrypted with ``target_key`` (or plaintext)."""
    import sqlcipher3
    target.unlink(missing_ok=True)
    conn = sqlcipher3.connect(str(source))
    try:
        if source_key:
            conn.execute(f"PRAGMA key = \"x'{source_key}'\"")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        attach_key = f"x'{target_key}'" if target_key else ""
        conn.execute(f"ATTACH DATABASE ? AS target KEY \"{attach_key}\"", (str(target),))
        conn.execute("SELECT sqlcipher_export('target')")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.execute(f"PRAGMA target.user_version = {int(version)}")
        conn.execute("DETACH DATABASE target")
    finally:
        conn.close()


def snapshot(source: Path, source_key: str | None, target: Path, target_key: str | None) -> None:
    """Copy a possibly live database into ``target`` in the target mode.

    Two different SQLite builds must never open the same live WAL database
    in one process: their locks on the shared-memory file do not see each
    other (observed as a bus error under a concurrent writer). So a
    plaintext source is first snapshotted with the stdlib (``VACUUM INTO``)
    and only that standalone file is handed to SQLCipher. An encrypted
    source is only ever opened by SQLCipher, like everything else then.
    """
    if source_key is not None:
        export(source, source_key, target, target_key)
        return
    plain = target.with_name(target.name + ".plain-tmp")
    plain.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(str(source), timeout=5.0)) as conn:
            conn.execute("VACUUM INTO ?", (str(plain),))
        if target_key is None:
            os.replace(plain, target)
        else:
            export(plain, None, target, target_key)
    finally:
        plain.unlink(missing_ok=True)


def apply_pending(db_path: Path) -> str:
    """Run a pending conversion at start-up. Returns what happened."""
    db_path = Path(db_path)
    current = state(db_path)
    if not current["pending"] or not db_path.is_file():
        return "none"
    encrypt = current["pending"] == "encrypt"
    source_key = None if encrypt else get_key(DB_KEY_NAME)
    target_key = ensure_key(DB_KEY_NAME) if encrypt else None
    if integrity(db_path, source_key) != "ok":
        raise EncryptionUnavailable("转换前数据库完整性检查未通过，保持原样")
    expected = row_counts(db_path, source_key)
    tmp = db_path.with_name(db_path.name + ".convert-tmp")
    try:
        snapshot(db_path, source_key, tmp, target_key)
        if integrity(tmp, target_key) != "ok" or row_counts(tmp, target_key) != expected:
            raise EncryptionUnavailable("转换结果校验未通过，保持原样")
        for suffix in ("-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
        os.replace(tmp, db_path)
    finally:
        tmp.unlink(missing_ok=True)
    _write_state(db_path, "encrypted" if encrypt else "plaintext", None)
    return current["pending"]


def backup_key() -> str | None:
    """Backups are encrypted whenever a persistent key store exists."""
    return ensure_key(BACKUP_KEY_NAME) if available() else None


__all__ = ["BACKUP_KEY_NAME", "DB_KEY_NAME", "EncryptionUnavailable", "apply_pending", "available", "backup_key",
           "connect", "connect_db", "db_key", "ensure_key", "export", "get_key", "integrity", "is_plaintext_file",
           "key_for_file", "request_change", "row_counts", "snapshot", "sqlcipher_available", "state", "use_keystore"]

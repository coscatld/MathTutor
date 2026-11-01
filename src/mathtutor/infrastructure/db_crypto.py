"""Encryption at rest with SQLCipher: opt-in for the database, always for backups.

The product database stays plaintext unless the student turns encryption on.
Turning it on (or off) only records a pending change; the conversion runs at
the next start, before anything opens the database:

    verify source -> export into a temporary file in the target mode ->
    durable intent + recovery copy -> verified export -> atomic swap -> marker

A startup journal resolves a swap whose marker was not committed. Recovery
material remains until both the actual file and marker are confirmed.

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
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from mathtutor.infrastructure.migration_lock import migration_lock

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
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(data, dict) and data.get("mode") in {"plaintext", "encrypted"}
                    and data.get("pending") in {None, "encrypt", "decrypt"}):
                return {"mode": data["mode"], "pending": data.get("pending")}
        except (OSError, ValueError, TypeError):
            raise EncryptionUnavailable("加密状态记录无法读取，已保留数据库和恢复材料") from None
        raise EncryptionUnavailable("加密状态记录无效，已保留数据库和恢复材料")
    return {"mode": "plaintext", "pending": None}


def _sync_directory(path: Path) -> None:
    # Windows has no portable directory fsync. Files are flushed and handles
    # closed before replace there; POSIX also persists directory entries.
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _atomic_json(path: Path, data: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _write_state(db_path: Path, mode: str, pending: str | None) -> None:
    _atomic_json(marker_path(db_path), {"mode": mode, "pending": pending})


def request_change(db_path: Path, enabled: bool) -> dict:
    """Record the wanted mode; the conversion runs at the next start."""
    db_path = Path(db_path).resolve()
    with migration_lock(db_path):
        if conversion_path(db_path).exists():
            raise EncryptionUnavailable("上次加密转换尚待启动恢复，请先重启完成恢复")
        return _request_change_locked(db_path, enabled)


def _request_change_locked(db_path: Path, enabled: bool) -> dict:
    current = state(db_path)
    wanted = "encrypted" if enabled else "plaintext"
    if enabled:
        if not available():
            raise EncryptionUnavailable("当前环境缺少 SQLCipher 或系统密钥存储，无法加密")
        if current["mode"] == "encrypted":
            _conversion_key()
        else:
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
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
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
        descriptor = os.open(plain, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(str(source), timeout=5.0)) as conn:
            conn.execute("VACUUM INTO ?", (str(plain),))
        if target_key is None:
            os.replace(plain, target)
        else:
            export(plain, None, target, target_key)
    finally:
        plain.unlink(missing_ok=True)


def conversion_path(db_path: Path) -> Path:
    return Path(f"{db_path}.conversion.json")


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _conversion_key() -> str:
    # request_change creates the key. A startup/recovery must never create a
    # replacement key when the credential entry needed by existing files is lost.
    key = get_key(DB_KEY_NAME)
    if not key or not sqlcipher_available():
        raise EncryptionUnavailable("加密转换需要原有密钥和 SQLCipher，已保留数据库和恢复材料")
    return key


def _read_conversion(db_path: Path) -> dict | None:
    path = conversion_path(db_path)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        operation = record["operation"]
        valid = (
            record["version"] == 1
            and isinstance(operation, str) and len(operation) == 32
            and all(c in "0123456789abcdef" for c in operation)
            and record["source_mode"] in {"plaintext", "encrypted"}
            and record["target_mode"] in {"plaintext", "encrypted"}
            and record["source_mode"] != record["target_mode"]
            and record["phase"] in {"preparing", "ready"}
            and isinstance(record["counts"], dict)
            and all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in record["counts"].items())
            and isinstance(record["source_sha256"], str) and len(record["source_sha256"]) == 64
            and (record["phase"] != "ready" or
                 isinstance(record["target_sha256"], str) and len(record["target_sha256"]) == 64)
        )
        if valid:
            return record
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raise EncryptionUnavailable("加密转换恢复记录无效，已保留数据库和恢复材料")


def _conversion_files(db_path: Path, record: dict) -> tuple[Path, Path]:
    # Only derived sibling paths: journal contents cannot select arbitrary files.
    stem = f"{db_path.name}.{record['operation']}"
    return db_path.with_name(stem + ".convert-tmp"), db_path.with_name(stem + ".convert-recovery")


def _matches(path: Path, key: str | None, fingerprint: str, counts: dict) -> bool:
    return (path.is_file() and _fingerprint(path) == fingerprint
            and integrity(path, key) == "ok" and row_counts(path, key) == counts)


def _cleanup_conversion(db_path: Path, record: dict) -> None:
    temporary, recovery = _conversion_files(db_path, record)
    plain = temporary.with_name(temporary.name + ".plain-tmp")
    for path in (temporary, recovery, plain):
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
    # Engines must not open until the journal is gone. If cleanup fails, the
    # next startup can still recognize the verified target without its backup.
    _sync_directory(db_path.parent)
    conversion_path(db_path).unlink()
    _sync_directory(db_path.parent)


def _replace_database(temporary: Path, db_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    os.replace(temporary, db_path)
    _sync_directory(db_path.parent)


def _recover_conversion(db_path: Path, record: dict) -> str:
    key = _conversion_key()
    source_key = key if record["source_mode"] == "encrypted" else None
    target_key = key if record["target_mode"] == "encrypted" else None
    temporary, recovery = _conversion_files(db_path, record)
    counts = record["counts"]
    if record["phase"] == "ready":
        if _matches(db_path, target_key, record["target_sha256"], counts):
            _write_state(db_path, record["target_mode"], None)
            _cleanup_conversion(db_path, record)
            return "encrypt" if target_key else "decrypt"
        if (_matches(db_path, source_key, record["source_sha256"], counts)
                and _matches(temporary, target_key, record["target_sha256"], counts)):
            _replace_database(temporary, db_path)
            _write_state(db_path, record["target_mode"], None)
            _cleanup_conversion(db_path, record)
            return "encrypt" if target_key else "decrypt"
    # No verified replacement was committed. A pre-export crash can discard
    # partial output only after the unchanged source has been checked.
    if _matches(db_path, source_key, record["source_sha256"], counts):
        _write_state(db_path, record["source_mode"], "encrypt" if target_key else "decrypt")
        _cleanup_conversion(db_path, record)
        return "retry"
    if _matches(recovery, source_key, record["source_sha256"], counts):
        # Keep the recovery point until marker commit and cleanup succeed.
        shutil.copyfile(recovery, temporary)
        temporary.chmod(0o600)
        _sync_file(temporary)
        _replace_database(temporary, db_path)
        _write_state(db_path, record["source_mode"], "encrypt" if target_key else "decrypt")
        _cleanup_conversion(db_path, record)
        raise EncryptionUnavailable("加密转换未完成，已恢复原数据库；请重启重试转换")
    raise EncryptionUnavailable("加密转换文件无法确认，已保留数据库和恢复材料，请先恢复数据")


def apply_pending(db_path: Path) -> str:
    """Convert/recover under the same OS-owned lock as startup migrations."""
    db_path = Path(db_path).resolve()
    with migration_lock(db_path):
        return _apply_pending_locked(db_path)


def _apply_pending_locked(db_path: Path) -> str:
    """Startup coordinator owns migration_lock throughout this and migrations."""
    record = _read_conversion(db_path)
    if record is not None:
        recovered = _recover_conversion(db_path, record)
        if recovered != "retry":
            return recovered
    current = state(db_path)
    if not current["pending"] or not db_path.is_file():
        return "none"
    encrypt = current["pending"] == "encrypt"
    if current["mode"] != ("plaintext" if encrypt else "encrypted"):
        raise EncryptionUnavailable("加密转换方向与状态记录不一致，已保留原数据")
    key = _conversion_key()
    source_key = None if encrypt else key
    target_key = key if encrypt else None
    if integrity(db_path, source_key) != "ok":
        raise EncryptionUnavailable("转换前数据库完整性检查未通过，保持原样")
    # Materialize any WAL before taking a byte-identical protected copy.
    with closing(connect(db_path, key=source_key)) as connection:
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and checkpoint[0]:
            raise EncryptionUnavailable("数据库仍在使用中，无法开始加密转换")
    expected = row_counts(db_path, source_key)
    _sync_file(db_path)
    record = {
        "version": 1, "operation": secrets.token_hex(16), "phase": "preparing",
        "source_mode": current["mode"], "target_mode": "encrypted" if encrypt else "plaintext",
        "counts": expected, "source_sha256": _fingerprint(db_path),
    }
    _atomic_json(conversion_path(db_path), record)
    temporary, recovery = _conversion_files(db_path, record)
    try:
        # O_EXCL and 0600 prevent transient plaintext recovery material from
        # receiving the user's normal, potentially permissive, file mode.
        descriptor = os.open(recovery, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as target, db_path.open("rb") as source:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        if not _matches(recovery, source_key, record["source_sha256"], expected):
            raise EncryptionUnavailable("转换保护副本校验未通过，保持原样")
        # Precreate with restrictive permissions before SQLite opens it.
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        snapshot(db_path, source_key, temporary, target_key)
        temporary.chmod(0o600)
        if integrity(temporary, target_key) != "ok" or row_counts(temporary, target_key) != expected:
            raise EncryptionUnavailable("转换结果校验未通过，保持原样")
        _sync_file(temporary)
        record = {**record, "phase": "ready", "target_sha256": _fingerprint(temporary)}
        _atomic_json(conversion_path(db_path), record)
    except Exception:
        # No swap can have happened before ready. Retain material if the source
        # cannot be verified; otherwise a normal export failure can retry cleanly.
        if _matches(db_path, source_key, record["source_sha256"], expected):
            _cleanup_conversion(db_path, record)
        raise
    _replace_database(temporary, db_path)
    _write_state(db_path, "encrypted" if encrypt else "plaintext", None)
    _cleanup_conversion(db_path, record)
    return current["pending"]


def backup_key() -> str | None:
    """Backups are encrypted whenever a persistent key store exists."""
    return ensure_key(BACKUP_KEY_NAME) if available() else None


__all__ = ["BACKUP_KEY_NAME", "DB_KEY_NAME", "EncryptionUnavailable", "apply_pending", "available", "backup_key",
           "connect", "connect_db", "db_key", "ensure_key", "export", "get_key", "integrity", "is_plaintext_file",
           "key_for_file", "request_change", "row_counts", "snapshot", "sqlcipher_available", "state", "use_keystore"]

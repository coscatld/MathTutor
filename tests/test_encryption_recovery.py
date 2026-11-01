"""Real SQLCipher fault injection across database/marker commits and startup locks."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from mathtutor.infrastructure import db_crypto
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure.migration_lock import migration_lock
from mathtutor.infrastructure.secret_store import InMemorySecretStore


TEST_KEY = "a" * 64  # Synthetic test-only credential, also used by child workers.


def database(tmp_path, encrypted):
    store = InMemorySecretStore()
    db_crypto._run(store.put(db_crypto.DB_KEY_NAME, TEST_KEY))
    db_crypto.use_keystore(store)
    path = tmp_path / "中文数据.db"
    upgrade_db(str(path))
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE recovery_sentinel (value TEXT)")
        connection.executemany("INSERT INTO recovery_sentinel VALUES (?)", [("原文保留",), ("42",)])
    if encrypted:
        db_crypto.request_change(path, True)
        assert db_crypto.apply_pending(path) == "encrypt"
    db_crypto.request_change(path, not encrypted)
    return path


def assert_content(path, encrypted):
    assert db_crypto.state(path) == {"mode": "encrypted" if encrypted else "plaintext", "pending": None}
    assert db_crypto.is_plaintext_file(path) is not encrypted
    with closing(db_crypto.connect_db(path)) as connection:
        assert connection.execute("SELECT value FROM recovery_sentinel").fetchall() == [("原文保留",), ("42",)]
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [("024",)]
    assert not db_crypto.conversion_path(path).exists()
    assert not list(path.parent.glob("*.convert-*"))


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("after_commit", [False, True])
def test_marker_write_failure_after_swap_recovers_actual_format(tmp_path, monkeypatch, encrypted, after_commit):
    path = database(tmp_path, encrypted)
    original = db_crypto._write_state

    def fail_marker(path, mode, pending):
        if after_commit:
            original(path, mode, pending)
        raise OSError("injected marker failure")

    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "_write_state", fail_marker)
        with pytest.raises(OSError, match="injected marker"):
            db_crypto.apply_pending(path)
    record = json.loads(db_crypto.conversion_path(path).read_text())
    assert record["phase"] == "ready"
    assert list(tmp_path.glob("*.convert-recovery")), "keep recovery point until marker commit is confirmed"
    assert db_crypto.is_plaintext_file(path) is encrypted
    assert db_crypto.apply_pending(path) == ("decrypt" if encrypted else "encrypt")
    assert_content(path, not encrypted)


@pytest.mark.parametrize("encrypted", [False, True])
def test_database_replace_failure_leaves_verified_target_for_restart(tmp_path, monkeypatch, encrypted):
    path = database(tmp_path, encrypted)
    original = db_crypto.os.replace

    def fail_replace(source, target):
        if Path(target) == path:
            raise OSError("injected database replace")
        return original(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(db_crypto.os, "replace", fail_replace)
        with pytest.raises(OSError, match="database replace"):
            db_crypto.apply_pending(path)
    assert db_crypto.is_plaintext_file(path) is not encrypted
    assert db_crypto.conversion_path(path).is_file()
    db_crypto.apply_pending(path)
    assert_content(path, not encrypted)


@pytest.mark.parametrize("encrypted", [False, True])
def test_missing_key_preserves_journal_and_files_without_generating_key(tmp_path, monkeypatch, encrypted):
    path = database(tmp_path, encrypted)
    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "_write_state", lambda *args: (_ for _ in ()).throw(OSError("marker")))
        with pytest.raises(OSError):
            db_crypto.apply_pending(path)
    materials = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    empty = InMemorySecretStore()
    db_crypto.use_keystore(empty)
    with pytest.raises(db_crypto.EncryptionUnavailable, match="原有密钥"):
        db_crypto.apply_pending(path)
    assert db_crypto._run(empty.get(db_crypto.DB_KEY_NAME)) is None
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == materials
    db_crypto._run(empty.put(db_crypto.DB_KEY_NAME, TEST_KEY))
    db_crypto.apply_pending(path)
    assert_content(path, not encrypted)


@pytest.mark.parametrize("encrypted", [False, True])
def test_unverifiable_replacement_restores_protected_source_and_stays_closed(tmp_path, monkeypatch, encrypted):
    path = database(tmp_path, encrypted)
    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "_write_state", lambda *args: (_ for _ in ()).throw(OSError("marker")))
        with pytest.raises(OSError):
            db_crypto.apply_pending(path)
    path.write_bytes(b"injected corrupt replacement")
    with pytest.raises(db_crypto.EncryptionUnavailable, match="已恢复原数据库"):
        db_crypto.apply_pending(path)
    assert db_crypto.state(path)["mode"] == ("encrypted" if encrypted else "plaintext")
    with closing(db_crypto.connect_db(path)) as connection:
        assert connection.execute("SELECT count(*) FROM recovery_sentinel").fetchone() == (2,)
    db_crypto.apply_pending(path)
    assert_content(path, not encrypted)


WORKER = r'''
from pathlib import Path
import sys, time
from mathtutor.infrastructure import db_crypto
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure.secret_store import InMemorySecretStore
root, phase, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
path = root / '中文数据.db'
store = InMemorySecretStore()
db_crypto._run(store.put(db_crypto.DB_KEY_NAME, 'a' * 64))
db_crypto.use_keystore(store)
def pause():
    (root / 'paused').touch()
    deadline = time.monotonic() + 20
    while not (root / 'resume').exists():
        assert time.monotonic() < deadline, 'coordinator timeout'
        time.sleep(.01)
if phase == 'after-swap':
    original = db_crypto._write_state
    def marker(*args):
        pause()
        return original(*args)
    db_crypto._write_state = marker
elif phase == 'ready':
    original = db_crypto._atomic_json
    def journal(target, data):
        result = original(target, data)
        if target == db_crypto.conversion_path(path) and data.get('phase') == 'ready':
            pause()
        return result
    db_crypto._atomic_json = journal
elif phase == 'preparing':
    original = db_crypto.snapshot
    def snapshot(*args):
        pause()
        return original(*args)
    db_crypto.snapshot = snapshot
(root / (name + '-attempt')).touch()
upgrade_db(str(path))
(root / (name + '-complete')).touch()
'''


def wait_file(path):
    deadline = time.monotonic() + 12
    while not path.exists():
        assert time.monotonic() < deadline, f"worker did not reach {path.name}"
        time.sleep(.01)


def worker(root, phase, name):
    return subprocess.Popen([sys.executable, "-c", WORKER, str(root), phase, name],
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def finish(process):
    output, error = process.communicate(timeout=20)
    assert process.returncode == 0, (output, error)


def stop(process):
    if process is not None:
        if process.poll() is None:
            process.kill()
        process.communicate()


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("phase", ["preparing", "ready", "after-swap"])
def test_process_termination_resumes_verified_conversion(tmp_path, encrypted, phase):
    path = database(tmp_path, encrypted)
    process = worker(tmp_path, phase, "first")
    try:
        wait_file(tmp_path / "paused")
        with pytest.raises(TimeoutError):
            with migration_lock(path, timeout=.1):
                pytest.fail("conversion must retain startup writer lock")
        process.kill()
        process.communicate(timeout=5)
        assert db_crypto.conversion_path(path).exists()
        upgrade_db(str(path))
        assert_content(path, not encrypted)
    finally:
        stop(process)


@pytest.mark.parametrize("encrypted", [False, True])
def test_two_startups_share_conversion_and_migration_writer_boundary(tmp_path, encrypted):
    path = database(tmp_path, encrypted)
    first = worker(tmp_path, "ready", "first")
    second = None
    try:
        wait_file(tmp_path / "paused")
        second = worker(tmp_path, "normal", "second")
        wait_file(tmp_path / "second-attempt")
        with pytest.raises(TimeoutError):
            with migration_lock(path, timeout=.1):
                pytest.fail("conversion and migration must share the writer lock")
        assert not (tmp_path / "second-complete").exists()
        assert len(list(tmp_path.glob("*.convert-tmp"))) == 1
        (tmp_path / "resume").touch()
        finish(first)
        finish(second)
        assert_content(path, not encrypted)
    finally:
        stop(first)
        stop(second)


def test_invalid_marker_and_journal_fail_closed(tmp_path):
    path = database(tmp_path, False)
    before = path.read_bytes()
    db_crypto.marker_path(path).write_text('{"mode":"unknown"}')
    with pytest.raises(db_crypto.EncryptionUnavailable, match="状态记录无效"):
        upgrade_db(str(path))
    assert path.read_bytes() == before
    db_crypto.conversion_path(path).write_text('{"operation":"../outside"}')
    with pytest.raises(db_crypto.EncryptionUnavailable, match="恢复记录无效"):
        upgrade_db(str(path))
    assert path.read_bytes() == before


def test_partial_plaintext_export_is_removed_only_after_source_validation(tmp_path, monkeypatch):
    path = database(tmp_path, False)

    class SimulatedProcessExit(BaseException):
        pass

    with monkeypatch.context() as patch:
        def crash(source, source_key, target, target_key):
            target.with_name(target.name + ".plain-tmp").write_text("partial plaintext")
            raise SimulatedProcessExit()
        patch.setattr(db_crypto, "snapshot", crash)
        with pytest.raises(SimulatedProcessExit):
            db_crypto.apply_pending(path)
    assert list(tmp_path.glob("*.plain-tmp"))
    with pytest.raises(db_crypto.EncryptionUnavailable, match="尚待启动恢复"):
        db_crypto.request_change(path, False)
    db_crypto.apply_pending(path)
    assert_content(path, True)
    assert not list(tmp_path.glob("*.plain-tmp"))


def test_bad_target_and_bad_recovery_never_change_marker_or_delete_material(tmp_path, monkeypatch):
    path = database(tmp_path, False)
    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "_write_state", lambda *args: (_ for _ in ()).throw(OSError("marker")))
        with pytest.raises(OSError):
            db_crypto.apply_pending(path)
    path.write_bytes(b"bad target")
    recovery, = tmp_path.glob("*.convert-recovery")
    recovery.write_bytes(b"bad recovery")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with pytest.raises(db_crypto.EncryptionUnavailable, match="无法确认"):
        upgrade_db(str(path))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


@pytest.mark.parametrize("encrypted", [False, True])
def test_cleanup_interruption_after_recovery_copy_removal_can_finish_target(tmp_path, monkeypatch, encrypted):
    path = database(tmp_path, encrypted)
    def partial_cleanup(path, record):
        _, recovery = db_crypto._conversion_files(path, record)
        recovery.unlink(missing_ok=True)
        raise OSError("injected cleanup interruption")
    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "_cleanup_conversion", partial_cleanup)
        with pytest.raises(OSError, match="cleanup interruption"):
            db_crypto.apply_pending(path)
    assert db_crypto.conversion_path(path).exists()
    db_crypto.apply_pending(path)
    assert_content(path, not encrypted)


@pytest.mark.parametrize("encrypted", [False, True])
def test_marker_failure_after_fallback_source_restore_can_resume(tmp_path, monkeypatch, encrypted):
    path = database(tmp_path, encrypted)
    def fail_marker(*args):
        raise OSError("injected marker interruption")
    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "_write_state", fail_marker)
        with pytest.raises(OSError):
            db_crypto.apply_pending(path)
    path.write_bytes(b"injected damaged replacement")
    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "_write_state", fail_marker)
        with pytest.raises(OSError):
            db_crypto.apply_pending(path)
    assert db_crypto.conversion_path(path).exists()
    db_crypto.apply_pending(path)
    assert_content(path, not encrypted)

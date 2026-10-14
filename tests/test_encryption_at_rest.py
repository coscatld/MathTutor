"""Opt-in SQLCipher database encryption and always-encrypted backups."""
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from mathtutor.api.product_state import reset_product_state
from mathtutor.infrastructure import db_crypto
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from test_phase6_main_integration import _client, _cycle_count, _submit_solved_problem

ENC = "/api/v2/math-tutor/desktop/privacy/encryption"
BACKUP = "/api/v2/math-tutor/desktop/backup"


def plaintext_readable(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return True
    except sqlite3.DatabaseError:
        return False


def test_turning_encryption_on_and_off_converts_at_the_next_start(tmp_path):
    db = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "enc-a")
        assert client.get(ENC).json()["mode"] == "plaintext"
        switched = client.put(ENC, json={"enabled": True}).json()
        assert switched["pending"] == "encrypt" and switched["restart_required"] is True
    reset_product_state()
    assert db_crypto.apply_pending(db) == "encrypt"
    assert not plaintext_readable(db) and b"tutoring_cycles" not in db.read_bytes()
    with _client(db) as client:
        assert client.get(ENC).json() == {**client.get(ENC).json(), "mode": "encrypted", "pending": None}
        _submit_solved_problem(client, "x + 1 = 2", "1", "enc-b")
    reset_product_state()
    with closing(db_crypto.connect_db(db)) as conn:
        assert conn.execute("SELECT count(*) FROM tutoring_cycles").fetchone()[0] == 2
    with _client(db) as client:
        assert client.put(ENC, json={"enabled": False}).json()["pending"] == "decrypt"
    reset_product_state()
    assert db_crypto.apply_pending(db) == "decrypt"
    assert plaintext_readable(db) and _cycle_count(db) == 2


def test_backups_are_encrypted_and_restore_needs_the_recovery_key_once_the_key_is_gone(tmp_path):
    db = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "enc-backup")
        name = client.post(BACKUP, json={}).json()["backup"]["path"]
        recovery_key = client.post(ENC + "/recovery-key").json()["recovery_key"]
    reset_product_state()
    backup = tmp_path / "backups" / name
    assert backup.is_file() and not plaintext_readable(backup)
    with _client(db) as client:
        _submit_solved_problem(client, "x + 1 = 2", "1", "enc-later")
    reset_product_state()

    db_crypto.use_keystore(InMemorySecretStore())  # the key store entry is gone
    with _client(db) as client:
        refused = client.post(BACKUP + "/restore", json={"path": name}).json()
        assert refused["ok"] is False
    reset_product_state()
    assert _cycle_count(db) == 2, "a refused restore leaves the database untouched"
    with _client(db) as client:
        restored = client.post(BACKUP + "/restore", json={"path": name, "recovery_key": recovery_key}).json()
        assert restored["ok"] is True
    reset_product_state()
    assert _cycle_count(db) == 1


def test_a_failed_conversion_keeps_the_original_and_the_marker(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE t(a)")
        conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
    db_crypto.request_change(db, True)
    before = db.read_bytes()
    monkeypatch.setattr(db_crypto, "row_counts", lambda path, key: {"t": 50} if key is None else {"t": 49})
    with pytest.raises(db_crypto.EncryptionUnavailable):
        db_crypto.apply_pending(db)
    assert db.read_bytes() == before and db_crypto.state(db)["pending"] == "encrypt"
    assert not list(tmp_path.glob("*.convert-tmp"))


def test_without_a_persistent_key_store_encryption_cannot_be_turned_on(tmp_path, monkeypatch):
    db = tmp_path / "math_tutor.db"
    monkeypatch.setattr(db_crypto, "_store", lambda: None)
    reset_product_state()
    with _client(db) as client:
        status = client.get(ENC).json()
        assert status["available"] is False and status["backups_encrypted"] is False
        assert client.put(ENC, json={"enabled": True}).status_code == 409
        created = client.post(BACKUP, json={}).json()
        assert created["ok"] is True
    reset_product_state()
    assert plaintext_readable(tmp_path / "backups" / created["backup"]["path"])

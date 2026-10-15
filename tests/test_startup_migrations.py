"""Regression coverage for fresh-install races and the observed 024/023 state."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from mathtutor.infrastructure import db_crypto
from mathtutor.infrastructure.migrate import alembic_config, upgrade_db
from mathtutor.infrastructure.migration_lock import migration_lock


def revisions(path):
    with closing(db_crypto.connect(path, key=db_crypto.key_for_file(path))) as connection:
        return connection.execute("SELECT version_num FROM alembic_version ORDER BY version_num").fetchall()


def damaged_database(path):
    upgrade_db(str(path))
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO alembic_version VALUES ('023')")
        connection.execute("CREATE TABLE repair_sentinel (value TEXT)")
        connection.execute("INSERT INTO repair_sentinel VALUES ('保留原数据')")
        connection.commit()


@pytest.mark.parametrize("encrypted", [False, True])
def test_recover_observed_heads_only_after_backup_and_preserve_data(tmp_path, encrypted):
    path = tmp_path / "蛋蛋的app" / "math_tutor.db"
    damaged_database(path)
    if encrypted:
        db_crypto.request_change(path, True)
        db_crypto.apply_pending(path)
    upgrade_db(str(path))
    assert revisions(path) == [("024",)]
    backup, = (path.parent / "backups").glob("*.sqlite3")
    assert revisions(backup) == [("023",), ("024",)]
    for database in (path, backup):
        with closing(db_crypto.connect(database, key=db_crypto.key_for_file(database))) as connection:
            assert connection.execute("SELECT value FROM repair_sentinel").fetchall() == [("保留原数据",)]
    upgrade_db(str(path))
    assert len(list((path.parent / "backups").glob("*.sqlite3"))) == 1


@pytest.mark.parametrize("damage", [
    "DROP TABLE turn_traces",
    "ALTER TABLE turn_traces DROP COLUMN details",
    "DROP TABLE knowledge_citation_receipts",
    "DROP TABLE conversations",
])
def test_incomplete_schema_is_not_stamped_as_recovered(tmp_path, damage):
    path = tmp_path / "math_tutor.db"
    damaged_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(damage)
        connection.commit()
    with pytest.raises(RuntimeError, match="结构校验未通过"):
        upgrade_db(str(path))
    assert revisions(path) == [("023",), ("024",)]
    backup, = (tmp_path / "backups").glob("*.sqlite3")
    assert revisions(backup) == revisions(path)


def test_unknown_heads_and_failed_backup_leave_original_versions(tmp_path, monkeypatch):
    path = tmp_path / "math_tutor.db"
    damaged_database(path)
    def fail(*args):
        raise OSError("backup sentinel")
    with monkeypatch.context() as patch:
        patch.setattr(db_crypto, "snapshot", fail)
        with pytest.raises(OSError, match="backup sentinel"):
            upgrade_db(str(path))
    assert revisions(path) == [("023",), ("024",)]
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'future' WHERE version_num = '023'")
        connection.commit()
    with pytest.raises(RuntimeError, match="无法自动恢复"):
        upgrade_db(str(path))
    assert revisions(path) == [("024",), ("future",)]


def test_failed_migration_rolls_back_schema_and_version_together(tmp_path, monkeypatch):
    from alembic import command
    from alembic.script import ScriptDirectory
    path = tmp_path / "math_tutor.db"
    command.upgrade(alembic_config(str(path)), "023")
    with closing(sqlite3.connect(path)) as connection:
        # Fresh metadata already contains 024's table. Simulate a real 023 DB.
        connection.execute("DROP TABLE turn_traces")
        connection.commit()
    script = ScriptDirectory.from_config(alembic_config(str(path)))
    original = script.get_revision("024").module.upgrade
    def fail():
        original()
        raise RuntimeError("after DDL sentinel")
    monkeypatch.setattr(script.get_revision("024").module, "upgrade", fail)
    monkeypatch.setattr(ScriptDirectory, "from_config", lambda cfg: script)
    with pytest.raises(RuntimeError, match="after DDL sentinel"):
        upgrade_db(str(path))
    assert revisions(path) == [("023",)]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='turn_traces'").fetchone() is None


WORKER = r'''
import os
from pathlib import Path
import sys
import time
from alembic.runtime.migration import MigrationContext
from mathtutor.infrastructure import db_crypto
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.infrastructure.migrate import upgrade_db
db_crypto.use_keystore(InMemorySecretStore())
root, mode = Path(sys.argv[1]), sys.argv[2]
if mode == 'first':
    original = MigrationContext.get_current_heads
    paused = False
    def heads(self):
        global paused
        value = original(self)
        if not value and not paused:
            paused = True
            (root / 'empty-head-read').touch()
            deadline = time.monotonic() + 15
            while not (root / 'resume').exists():
                assert time.monotonic() < deadline, 'coordinator timeout'
                time.sleep(.02)
        return value
    MigrationContext.get_current_heads = heads
(root / (mode + '-attempt')).touch()
upgrade_db(str(root / '中文数据' / 'math_tutor.db'))
'''


def wait_file(path):
    deadline = time.monotonic() + 12
    while not path.exists():
        assert time.monotonic() < deadline, f"worker did not reach {path.name}"
        time.sleep(.02)


def test_two_processes_serialize_the_exact_fresh_install_race(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    command = [sys.executable, "-c", WORKER, str(tmp_path)]
    first = subprocess.Popen(command + ["first"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = None
    path = tmp_path / "中文数据" / "math_tutor.db"
    try:
        wait_file(tmp_path / "empty-head-read")
        second = subprocess.Popen(command + ["second"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        wait_file(tmp_path / "second-attempt")
        with pytest.raises(TimeoutError, match="另一个 MathTutor"):
            with migration_lock(path, timeout=.15):
                pytest.fail("first migration did not retain its lock")
        (tmp_path / "resume").touch()
        for process in (first, second):
            out, err = process.communicate(timeout=20)
            assert process.returncode == 0, (out, err)
        assert revisions(path) == [("024",)]
    finally:
        (tmp_path / "resume").touch()
        for process in (first, second):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()


def test_os_releases_lock_after_process_termination(tmp_path):
    code = '''
import sys, time
from pathlib import Path
from mathtutor.infrastructure.migration_lock import migration_lock
root = Path(sys.argv[1])
with migration_lock(root / 'math_tutor.db'):
    (root / 'locked').touch()
    time.sleep(30)
'''
    process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)])
    try:
        wait_file(tmp_path / "locked")
        process.kill()
        process.wait(timeout=5)
        with migration_lock(tmp_path / "math_tutor.db", timeout=1):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def test_simultaneous_lock_file_creation_serializes_all_writers(tmp_path):
    code = '''
from pathlib import Path
import sys, time
from mathtutor.infrastructure.migration_lock import migration_lock
root, worker = Path(sys.argv[1]), sys.argv[2]
(root / ('ready-' + worker)).touch()
deadline = time.monotonic() + 15
while not (root / 'go').exists():
    assert time.monotonic() < deadline
    time.sleep(.01)
with migration_lock(root / 'math_tutor.db'):
    counter = root / 'counter'
    value = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(value + 1))
'''
    processes = [subprocess.Popen([sys.executable, "-c", code, str(tmp_path), str(index)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(6)]
    try:
        for index in range(6):
            wait_file(tmp_path / f"ready-{index}")
        (tmp_path / "go").touch()
        for process in processes:
            out, err = process.communicate(timeout=15)
            assert process.returncode == 0, (out, err)
        assert (tmp_path / "counter").read_text() == "6"
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()

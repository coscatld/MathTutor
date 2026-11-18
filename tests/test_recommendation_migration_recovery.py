"""Recover an actual historical 024 shape without requiring future tables."""
from contextlib import closing
import sqlite3

from alembic import command
import pytest

from mathtutor.infrastructure import db_crypto
from mathtutor.infrastructure.migrate import alembic_config, upgrade_db

LATER_TABLES = ("learning_loop_episodes", "exploration_inquiries", "exploration_generations",
                "knowledge_recommendations")


def historical_024(path):
    command.upgrade(alembic_config(str(path)), "024")
    # 001 deliberately uses current metadata. Remove later additions so this
    # fixture has 024's shape rather than a current schema with an old stamp.
    with closing(sqlite3.connect(path)) as conn:
        for table in LATER_TABLES:
            conn.execute(f'DROP TABLE "{table}"')
        for column in ("policy_id", "policy_version"):
            conn.execute(f'ALTER TABLE verification_logs DROP COLUMN "{column}"')
        conn.execute("INSERT INTO alembic_version VALUES ('023')")
        conn.execute("CREATE TABLE preserved_learner_note (body TEXT)")
        conn.execute("INSERT INTO preserved_learner_note VALUES ('keep this note')")
        conn.commit()


def versions(path):
    with closing(db_crypto.connect(path, key=db_crypto.key_for_file(path))) as conn:
        return conn.execute("SELECT version_num FROM alembic_version ORDER BY version_num").fetchall()


def test_recovery_upgrades_historical_024_to_028_and_preserves_original_backup(tmp_path):
    path = tmp_path / "historical.db"
    historical_024(path)
    with closing(sqlite3.connect(path)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names.intersection(LATER_TABLES)
        assert "policy_id" not in {row[1] for row in conn.execute("PRAGMA table_info(verification_logs)")}
    upgrade_db(str(path))
    assert versions(path) == [("028",)]
    backup, = (tmp_path / "backups").glob("*.sqlite3")
    assert versions(backup) == [("023",), ("024",)]
    with closing(sqlite3.connect(path)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(LATER_TABLES) <= names
        assert {"policy_id", "policy_version"} <= {row[1] for row in conn.execute("PRAGMA table_info(verification_logs)")}
        assert "lease_key" in {row[1] for row in conn.execute("PRAGMA table_info(knowledge_recommendations)")}
        assert conn.execute("SELECT body FROM preserved_learner_note").fetchone() == ("keep this note",)
    with closing(db_crypto.connect(backup, key=db_crypto.key_for_file(backup))) as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='knowledge_recommendations'").fetchall()
        assert conn.execute("SELECT body FROM preserved_learner_note").fetchone() == ("keep this note",)


@pytest.mark.parametrize("damage", [
    "ALTER TABLE turn_traces DROP COLUMN details",
    "CREATE TABLE knowledge_recommendations (student_id TEXT)",
    "CREATE TABLE exploration_inquiries (student_id TEXT)",
    "ALTER TABLE verification_logs ADD COLUMN policy_id INTEGER NOT NULL DEFAULT 0",
])
def test_recovery_still_rejects_missing_or_malformed_known_schema(tmp_path, damage):
    path = tmp_path / "damaged.db"
    historical_024(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(damage)
        conn.commit()
    with pytest.raises(RuntimeError, match="结构校验未通过"):
        upgrade_db(str(path))
    assert versions(path) == [("023",), ("024",)]
    backup, = (tmp_path / "backups").glob("*.sqlite3")
    assert versions(backup) == versions(path)

from pathlib import Path

import pytest

from mathtutor.infrastructure.db import create_db_engine
from mathtutor.release_probe import (
    document_retrieval_probe,
    migration_probe,
)


def test_migration_probe_returns_only_head(tmp_path: Path) -> None:
    db = tmp_path / "probe.db"
    import sqlite3

    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
    connection.execute("INSERT INTO alembic_version VALUES ('006')")
    connection.commit()
    connection.close()
    assert migration_probe(db) == {"head": "006"}


@pytest.mark.asyncio
async def test_document_probe_returns_safe_empty_shape(tmp_path: Path) -> None:
    db = tmp_path / "probe.db"
    engine = create_db_engine(db)
    try:
        async with engine.begin() as connection:
            # The real repository query needs the production tables; an empty
            # metadata-created DB is sufficient to exercise the safe shape.
            from mathtutor.infrastructure.schema import metadata

            await connection.run_sync(metadata.create_all)
        result = await document_retrieval_probe(db, "sentinel")
    finally:
        await engine.dispose()
    assert result == {"hit": False, "vector_used": False}
    assert "text" not in result

import asyncio
from pathlib import Path
import anyio
import pytest
from sqlalchemy import text
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.repositories.teaching_repository import TeachingRepository

@pytest.mark.asyncio
async def test_cancelled_transaction_releases_owner(tmp_path):
    engine=create_db_engine(tmp_path/'isolated.db')
    repo=TeachingRepository(engine)
    async with engine.begin() as connection:
        await connection.execute(text('CREATE TABLE cancellation_probe (value INTEGER)'))
    try:
        with anyio.CancelScope() as scope:
            async with repo.connection() as connection:
                await connection.execute(text('INSERT INTO cancellation_probe VALUES (1)'))
                scope.cancel()
                await anyio.lowlevel.checkpoint()
        assert engine.pool.checkedout()==0
        async with engine.connect() as connection:
            assert (await connection.execute(text('SELECT count(*) FROM cancellation_probe'))).scalar_one()==0
            result=(await connection.execute(text('PRAGMA wal_checkpoint(TRUNCATE)'))).first()
            assert result[0]==0
    finally:
        await engine.dispose()

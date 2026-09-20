"""Deterministic ownership checks: retained references must not retain handles."""
from contextlib import closing
import sqlite3
import asyncio

import pytest
from sqlalchemy import text

from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.api.product_state import ProductState


def test_repeated_migration_closes_owned_connections(tmp_path, monkeypatch):
    path = tmp_path / "isolated.db"
    upgrade_db(str(path))
    retained = []
    original = sqlite3.connect

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        retained.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        upgrade_db(str(path))
        assert retained
        for connection in retained:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
    finally:
        for connection in retained:
            connection.close()


@pytest.mark.asyncio
async def test_external_reader_blocks_restore_shutdown_without_deleting_sidecars(tmp_path):
    path = tmp_path / "isolated.db"
    upgrade_db(str(path))
    engine = create_db_engine(path)
    state = ProductState(engine=engine, db_path=path)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    try:
        with closing(sqlite3.connect(path)) as reader:
            reader.execute("SELECT * FROM alembic_version").fetchall()
            with pytest.raises(RuntimeError, match="owners|sidecars"):
                await state.shutdown_runtime()
            assert state.lifecycle_status == "FAILED"
            assert not await state.admit_request()
        await state.shutdown_runtime()
        await state.shutdown_runtime()
        assert state.lifecycle_status == "STOPPED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_shutdown_joins_cleanup_and_closes_admission():
    state = ProductState()
    entered, release = asyncio.Event(), asyncio.Event()
    class Worker:
        async def shutdown(self):
            entered.set()
            await release.wait()
    state.verification_backend = Worker()
    task = asyncio.create_task(state.shutdown_runtime())
    await entered.wait()
    assert not await state.admit_request()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.lifecycle_status == "STOPPED"
    await state.shutdown_runtime()


@pytest.mark.asyncio
async def test_failed_stage_preserves_first_error_and_still_disposes(tmp_path):
    path = tmp_path / "isolated.db"
    upgrade_db(str(path))
    engine = create_db_engine(path)
    state = ProductState(engine=engine, db_path=path)
    first = RuntimeError("injected first shutdown failure")
    class Worker:
        async def shutdown(self):
            raise first
    state.verification_backend = Worker()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    with pytest.raises(RuntimeError) as caught:
        await state.shutdown_runtime()
    assert caught.value is first
    assert state.lifecycle_status == "FAILED"
    assert engine.pool.checkedout() == 0
    assert engine.pool.checkedin() == 0


def test_partial_application_startup_releases_runtime(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import current_product_state, reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings
    reset_product_state()
    app = create_math_tutor_app(MathTutorSecuritySettings(environment="development", host="127.0.0.1"),
                                auth_enabled=False, db_path=str(tmp_path / "isolated.db"))
    state = current_product_state()
    async def fail():
        raise RuntimeError("startup sentinel")
    monkeypatch.setattr(state.verification_backend, "start", fail)
    try:
        with pytest.raises(RuntimeError, match="startup sentinel"):
            with TestClient(app):
                pass
        assert state.lifecycle_status == "STOPPED"
    finally:
        reset_product_state()


@pytest.mark.asyncio
async def test_cancelled_backup_waits_for_owned_thread_before_shutdown(tmp_path):
    import threading
    from mathtutor.infrastructure.backup import BackupService
    engine = create_db_engine(tmp_path / "isolated.db")
    service = BackupService(engine)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    def worker():
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
    task = asyncio.create_task(service._run_owned(worker))
    try:
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service._owned_workers
        stopping = asyncio.create_task(service.shutdown())
        release.set()
        await stopping
        assert not service._owned_workers
        with pytest.raises(RuntimeError, match="shutting down"):
            await service._run_owned(worker)
    finally:
        release.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_checked_out_connection_prevents_restore_and_can_be_released(tmp_path):
    from mathtutor.api.desktop_api import _restore_backup_while_quiesced
    path = tmp_path / "isolated.db"
    upgrade_db(str(path))
    engine = create_db_engine(path)
    state = ProductState(engine=engine, db_path=path)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        result = await _restore_backup_while_quiesced(state, tmp_path / "nonexistent.backup")
        assert result["ok"] is False
        assert state.lifecycle_status == "FAILED"
        assert engine.pool.checkedout() == 1
        assert not list(tmp_path.glob("*.rollback"))
    await state.shutdown_runtime()
    assert state.lifecycle_status == "STOPPED"


@pytest.mark.asyncio
async def test_failed_owned_loop_is_observable():
    from mathtutor.application.outbox_relay import OutboxRelayService
    relay = OutboxRelayService(None)
    sentinel = RuntimeError("owned loop failed")
    async def fail():
        raise sentinel
    relay._task = asyncio.create_task(fail())
    with pytest.raises(RuntimeError) as caught:
        await relay.stop()
    assert caught.value is sentinel


@pytest.mark.asyncio
async def test_normal_repeated_shutdown_releases_directory(tmp_path):
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from mathtutor.infrastructure.lifecycle_trace import trace
    directory = TemporaryDirectory(dir=tmp_path)
    path = Path(directory.name) / "isolated.db"
    upgrade_db(str(path))
    engine = create_db_engine(path)
    state = ProductState(engine=engine, db_path=path)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await state.shutdown_runtime()
        await state.shutdown_runtime()
        assert state.lifecycle_status == "STOPPED"
    finally:
        await engine.dispose()
        trace(id(state), "directory_cleanup_begin")
        directory.cleanup()
        trace(id(state), "directory_cleanup_complete")

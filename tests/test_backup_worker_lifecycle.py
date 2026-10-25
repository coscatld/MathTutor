"""Backup I/O must yield the event loop and drain before file replacement."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from mathtutor.infrastructure import backup as backup_module
from mathtutor.infrastructure.backup import (
    BackupManifest,
    BackupPolicy,
    BackupScheduler,
    BackupService,
)
from mathtutor.infrastructure.db import create_db_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def service(tmp_path):
    engine = create_db_engine(tmp_path / "source.db")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE sample (value TEXT)"))
        await conn.execute(text("INSERT INTO sample VALUES ('consistent snapshot')"))
    result = BackupService(engine)
    try:
        yield result
    finally:
        await result.shutdown()
        await engine.dispose()


async def _heartbeat() -> None:
    """A blocked I/O worker must permit repeated event-loop turns."""
    async def pulse():
        for _ in range(10):
            await asyncio.sleep(0)

    await asyncio.wait_for(pulse(), timeout=1.0)


async def test_slow_hash_and_manifest_io_run_off_loop(service, tmp_path, monkeypatch):
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    original_hash = backup_module._sha256
    original_write = BackupService._write_manifest_atomic
    writes = []

    def slow_hash(path):
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5.0), "test did not release hash worker"
        return original_hash(path)

    def write_manifest(path, manifest):
        assert threading.get_ident() != loop_thread
        writes.append(path)
        return original_write(path, manifest)

    monkeypatch.setattr(backup_module, "_sha256", slow_hash)
    monkeypatch.setattr(BackupService, "_write_manifest_atomic", staticmethod(write_manifest))
    path = tmp_path / "slow.backup-1.db"
    task = asyncio.create_task(service.create_backup(path))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10.0)
        await _heartbeat()
        assert not task.done()
        assert service._owned_workers
        release.set()
        manifest = await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)

    assert writes == [path.resolve()]
    assert manifest.sha256 == original_hash(path)
    assert manifest.size_bytes == path.stat().st_size
    assert json.loads(Path(f"{path}.manifest.json").read_text()) == manifest.to_dict()
    assert not service._owned_workers


async def test_cancelled_manifest_publication_drains_before_restore(
    service, tmp_path, monkeypatch
):
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    original_write = BackupService._write_manifest_atomic

    def delayed_write(path, manifest):
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5.0), "test did not release manifest worker"
        return original_write(path, manifest)

    monkeypatch.setattr(BackupService, "_write_manifest_atomic", staticmethod(delayed_write))
    backup = tmp_path / "cancelled.backup-1.db"
    sidecar = Path(f"{backup}.manifest.json")
    target = tmp_path / "restored.db"
    creating = asyncio.create_task(service.create_backup(backup))
    restoring = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=10.0)
        creating.cancel()
        with pytest.raises(asyncio.CancelledError):
            await creating
        assert service._owned_workers

        async def drain_then_restore():
            # ProductState uses this ordering before replacing the live DB.
            await service.shutdown()
            manifest = BackupManifest.from_dict(json.loads(sidecar.read_text()))
            return await service.restore(backup, target, manifest)

        restoring = asyncio.create_task(drain_then_restore())
        await _heartbeat()
        assert not restoring.done()
        assert not sidecar.exists()
        assert not target.exists()
        release.set()
        assert await restoring == target.resolve()
    finally:
        release.set()
        await asyncio.gather(creating, *([restoring] if restoring else []), return_exceptions=True)

    assert not service._owned_workers
    assert BackupService.verify_backup(backup, BackupManifest.from_dict(json.loads(sidecar.read_text())))[0]
    assert BackupService._verify_backup_file(target) == "ok"
    assert not list(tmp_path.glob("*.tmp-*"))


async def test_cancelled_scheduler_retention_stays_owned_until_shutdown(
    service, tmp_path, monkeypatch
):
    directory = tmp_path / "backups"
    manifest = await service.create_backup(backup_dir=directory)
    oldest = directory / "source.backup-old.db"
    oldest.write_bytes(b"older unverified backup")
    os.utime(oldest, (0, 0))
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    original_retention = BackupService.apply_retention

    def delayed_retention(path, limit):
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5.0), "test did not release retention worker"
        return original_retention(path, limit)

    async def already_created(**kwargs):
        return manifest

    monkeypatch.setattr(service, "create_backup", already_created)
    monkeypatch.setattr(BackupService, "apply_retention", staticmethod(delayed_retention))
    scheduler = BackupScheduler(
        service, BackupPolicy(mode="on_startup", backup_dir=directory, retention_limit=1)
    )
    stopping = None
    scheduler.start()
    try:
        await asyncio.wait_for(entered.wait(), timeout=10.0)
        await _heartbeat()
        await scheduler.stop(timeout=0.01)
        assert service._owned_workers
        stopping = asyncio.create_task(service.shutdown())
        await _heartbeat()
        assert not stopping.done()
        assert oldest.exists()
        release.set()
        await stopping
    finally:
        release.set()
        await scheduler.stop()
        if stopping:
            await stopping

    assert not service._owned_workers
    assert not oldest.exists()
    assert Path(manifest.backup_path).is_file()
    with pytest.raises(RuntimeError, match="shutting down"):
        await service.run_retention(directory, 1)

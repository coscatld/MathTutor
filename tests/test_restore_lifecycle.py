"""Restore cancellation owns every thread until file and runtime state agree."""
from __future__ import annotations

import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading

import pytest
import pytest_asyncio
from sqlalchemy import text

from mathtutor.api import desktop_api, product_state
from mathtutor.api.desktop_api import BackupPathRequest, restore_backup_endpoint
from mathtutor.api.product_state import ProductState, current_product_state, get_product_state, reset_product_state
from mathtutor.infrastructure import backup as backup_module, db_crypto, migrate
from mathtutor.infrastructure.backup import BackupError, BackupService

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world(tmp_path):
    reset_product_state()
    path = tmp_path / "product.db"
    migrate.upgrade_db(path)
    state = get_product_state(path)
    async with state.uow.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE restore_sentinel(value TEXT NOT NULL)"))
        await connection.execute(text("INSERT INTO restore_sentinel VALUES ('backup')"))
    manifest = await state.backup_service.create_backup(backup_dir=tmp_path / "backups")
    async with state.uow.engine.begin() as connection:
        await connection.execute(text("UPDATE restore_sentinel SET value='live'"))
    try:
        yield state, path, Path(manifest.backup_path)
    finally:
        current = current_product_state()
        if current is not None:
            await current.shutdown_runtime()
        reset_product_state()


def sentinel(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT value FROM restore_sentinel").fetchone()[0]


async def request_restore(state, backup):
    assert await state.admit_request()
    try:
        return await restore_backup_endpoint(BackupPathRequest(path=backup.name))
    finally:
        await state.release_request()


async def turns():
    for _ in range(8):
        await asyncio.sleep(0)


class Barrier:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.active = False
        self.finished = False

    def wait(self):
        self.active = True
        self.loop.call_soon_threadsafe(self.entered.set)
        try:
            assert self.release.wait(15), "test failed to release file worker"
        finally:
            self.active = False
            self.finished = True


async def test_cancelled_gate_acquisition_releases_only_its_own_marker():
    state = ProductState()
    assert await state.admit_request()  # restore
    assert await state.admit_request()  # another admitted request
    entered = asyncio.Event()
    original = state._maintenance_condition.wait_for
    async def waiting(predicate):
        entered.set()
        return await original(predicate)
    state._maintenance_condition.wait_for = waiting
    async def acquire():
        async with state.maintenance() as acquired:
            assert acquired
    task = asyncio.create_task(acquire())
    await entered.wait()
    assert not await state.admit_request()
    async with state._maintenance_condition:
        task.cancel()
        await turns()
        task.cancel()  # while the waiter must reacquire its condition lock
        await turns()
        assert not task.done()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not state._maintenance_active
    await state.release_request()
    assert await state.admit_request()
    await state.release_request()
    await state.release_request()


@pytest.mark.parametrize("stage", ["protect", "protect_after", "replace_before", "replace_after", "migrate_before", "migrate_after"])
@pytest.mark.parametrize("outcome", ["cancel", "oserror", "worker_cancel"])
async def test_file_worker_terminal_before_rebuild_or_rollback(world, monkeypatch, stage, outcome):
    state, path, backup = world
    barrier = Barrier()
    fired = False
    replacements = []
    copy = desktop_api.shutil.copy2
    replace = backup_module.os.replace
    upgrade = migrate.upgrade_db
    build = product_state._build_product_state

    def checkpoint():
        nonlocal fired
        fired = True
        barrier.wait()
        if outcome == "oserror":
            raise OSError("injected restore stage failure")
        if outcome == "worker_cancel":
            raise asyncio.CancelledError

    def copy_file(src, dst, *args, **kwargs):
        if stage == "protect" and ".pre-restore-" in Path(dst).name and not fired:
            checkpoint()
        result = copy(src, dst, *args, **kwargs)
        if stage == "protect_after" and ".pre-restore-" in Path(dst).name and not fired:
            checkpoint()
        return result

    def replace_file(src, dst, *args, **kwargs):
        selected = Path(dst) == path and ".tmp-" in Path(src).name and not fired
        if selected:
            replacements.append((str(src), str(dst)))
            if stage == "replace_before":
                checkpoint()
        result = replace(src, dst, *args, **kwargs)
        if selected and stage == "replace_after":
            checkpoint()
        return result

    def migration(target):
        if stage == "migrate_before":
            checkpoint()
        result = upgrade(target)
        if stage == "migrate_after":
            checkpoint()
        return result

    def build_when_idle(*args, **kwargs):
        assert not barrier.active and barrier.finished, "runtime opened before file worker finished"
        return build(*args, **kwargs)

    monkeypatch.setattr(desktop_api.shutil, "copy2", copy_file)
    monkeypatch.setattr(backup_module.os, "replace", replace_file)
    monkeypatch.setattr(migrate, "upgrade_db", migration)
    monkeypatch.setattr(product_state, "_build_product_state", build_when_idle)
    task = asyncio.create_task(request_restore(state, backup))
    try:
        await asyncio.wait_for(barrier.entered.wait(), 10)
        assert not await state.admit_request()
        # A second restore must not clear this gate or start another copy.
        refused = await restore_backup_endpoint(BackupPathRequest(path=backup.name))
        assert refused["ok"] is False
        assert state._maintenance_active
        if outcome == "cancel":
            task.cancel()
            await turns()
            task.cancel()
            await turns()
            assert not task.done()
            assert current_product_state() is state
        barrier.release.set()
        if outcome in {"cancel", "worker_cancel"}:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 20)
        else:
            result = await asyncio.wait_for(task, 20)
            assert result["ok"] is False
    finally:
        barrier.release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert barrier.finished and not state.backup_service._owned_workers
    assert sentinel(path) == ("backup" if outcome == "cancel" else "live")
    current = current_product_state()
    assert current is not state and current.lifecycle_status == "RUNNING"
    assert await current.admit_request()
    await current.release_request()
    assert not list(path.parent.glob("*.rollback"))
    assert not list(path.parent.glob("*.tmp-*"))


@pytest.mark.parametrize("failure", ["copy", "integrity", "rebuild"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_recovery_retains_protection_image_and_closes_admission(world, monkeypatch, failure, cancelled):
    state, path, backup = world
    copy = BackupService._copy_atomic
    verify = BackupService._verify_backup_file
    rollback_started = False
    def fail_migration(_):
        if cancelled:
            raise asyncio.CancelledError
        raise OSError("migration failed")
    def rollback_copy(source, target):
        nonlocal rollback_started
        if Path(source).suffix == ".rollback":
            rollback_started = True
            if failure == "copy":
                raise OSError("rollback replacement failed")
        return copy(source, target)
    def rollback_verify(target, *args):
        if failure == "integrity" and rollback_started and Path(target) == path:
            return "injected bad integrity"
        return verify(target, *args)
    def fail_build(*args, **kwargs):
        assert current_product_state() is state, "failed construction removed the closed gate"
        raise OSError("rebuild failed")
    monkeypatch.setattr(migrate, "upgrade_db", fail_migration)
    monkeypatch.setattr(BackupService, "_copy_atomic", staticmethod(rollback_copy))
    monkeypatch.setattr(BackupService, "_verify_backup_file", staticmethod(rollback_verify))
    if failure == "rebuild":
        monkeypatch.setattr(product_state, "_build_product_state", fail_build)
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await request_restore(state, backup)
    else:
        result = await request_restore(state, backup)
        assert result["ok"] is False and result["recovery_required"] is True
    assert current_product_state() is state
    assert state.lifecycle_status == "FAILED" and state._maintenance_active
    assert not await state.admit_request()
    recovery = state.restore_recovery_path
    assert recovery.is_file() and sentinel(recovery) == "live"
    assert verify(recovery) == "ok"
    # Shutdown must not reopen/checkpoint an uncertain target after its owned
    # resources were already closed, or delete the remaining recovery image.
    await state.shutdown_runtime()
    assert state.lifecycle_status == "FAILED" and recovery.exists()


async def test_rebuild_failure_after_replacement_rolls_back_before_retry(world, monkeypatch):
    state, path, backup = world
    build = product_state._build_product_state
    calls = []
    def fail_once(*args, **kwargs):
        calls.append(sentinel(path))
        assert current_product_state() is state
        if len(calls) == 1:
            raise OSError("initial rebuild failed")
        return build(*args, **kwargs)
    monkeypatch.setattr(product_state, "_build_product_state", fail_once)
    result = await request_restore(state, backup)
    assert result["ok"] is False
    assert calls == ["backup", "live"]
    assert sentinel(path) == "live" and not state.restore_recovery_path
    assert current_product_state() is not state


@pytest.mark.parametrize("pending", ["encrypt", "decrypt", "journal", "unreadable"])
async def test_encryption_transition_preflight_refuses_without_touching_runtime_or_files(world, pending):
    state, path, backup = world
    marker = db_crypto.marker_path(path)
    journal = db_crypto.conversion_path(path)
    if pending == "journal":
        journal.write_text('{"incomplete":"synthetic journal"}')
    elif pending == "unreadable":
        marker.write_text("not-json")
    else:
        marker.write_text(json.dumps({"mode": "plaintext", "pending": pending}))
    before = {p: p.read_bytes() for p in [path, marker, journal] if p.exists()}
    result = await request_restore(state, backup)
    assert result["ok"] is False and "未开始恢复" in result["message"]
    assert state.lifecycle_status == "RUNNING" and state._shutdown_task is None
    assert current_product_state() is state and not state._maintenance_active
    assert {p: p.read_bytes() for p in before} == before
    assert not list(path.parent.glob("*.rollback"))
    assert await state.admit_request()
    await state.release_request()


async def test_app_shutdown_captured_old_state_joins_replacement_even_when_cancelled(world, monkeypatch):
    state, path, backup = world
    barrier = Barrier()
    replace = backup_module.os.replace
    fired = False
    def paused_replace(source, target):
        nonlocal fired
        result = replace(source, target)
        if Path(target) == path and not fired:
            fired = True
            barrier.wait()
        return result
    monkeypatch.setattr(backup_module.os, "replace", paused_replace)
    restoring = asyncio.create_task(request_restore(state, backup))
    stopping = None
    try:
        await asyncio.wait_for(barrier.entered.wait(), 10)
        stopping = asyncio.create_task(state.shutdown_runtime())
        await turns()
        stopping.cancel()
        await turns()
        stopping.cancel()
        await turns()
        assert not stopping.done() and not restoring.done()
        barrier.release.set()
        assert (await asyncio.wait_for(restoring, 20))["ok"] is True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stopping, 20)
    finally:
        barrier.release.set()
        await asyncio.gather(restoring, *([stopping] if stopping else []), return_exceptions=True)
    current = current_product_state()
    assert current is not state and current.lifecycle_status == "STOPPED"
    assert not await current.admit_request()
    assert current.uow.engine.pool.checkedout() == 0
    assert current.uow.engine.pool.checkedin() == 0


async def test_service_restore_cancellation_joins_file_worker_and_rejects_second_restore(world, monkeypatch):
    state, path, backup = world
    await state.shutdown_runtime()
    barrier = Barrier()
    restore_into = BackupService._restore_into
    def paused_copy(*args):
        barrier.wait()
        return restore_into(*args)
    monkeypatch.setattr(BackupService, "_restore_into", staticmethod(paused_copy))
    restoring = asyncio.create_task(state.backup_service.restore_verified(backup, path))
    try:
        await asyncio.wait_for(barrier.entered.wait(), 10)
        restoring.cancel()
        await turns()
        restoring.cancel()
        await turns()
        assert not restoring.done() and state.backup_service._owned_workers
        with pytest.raises(BackupError, match="already running"):
            await state.backup_service.restore_verified(backup, path)
        barrier.release.set()
        with pytest.raises(asyncio.CancelledError):
            await restoring
    finally:
        barrier.release.set()
        await asyncio.gather(restoring, return_exceptions=True)
    assert sentinel(path) == "backup" and not state.backup_service._owned_workers

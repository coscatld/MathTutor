"""Health probes release their own pools and borrow the runtime's pool."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from mathtutor.infrastructure import db


@pytest.mark.asyncio
async def test_private_health_pool_closes_without_garbage_collection(tmp_path, monkeypatch):
    path = tmp_path / "health.db"
    owner = db.create_db_engine(path)
    retained = []
    create_engine = db.create_db_engine

    def create_health_engine():
        engine = create_engine(path)
        retained.append(engine)
        return engine

    monkeypatch.setattr(db, "create_db_engine", create_health_engine)
    try:
        async with owner.connect() as connection:
            await connection.execute(text("SELECT 1"))
        assert (await db.check_db_health())["status"] == "ok"
        assert len(retained) == 1
        assert retained[0].pool.checkedin() == 0
        await owner.dispose()
        assert not Path(f"{path}-wal").exists()
        assert not Path(f"{path}-shm").exists()
    finally:
        await owner.dispose()
        for engine in retained:
            await engine.dispose()


@pytest.mark.asyncio
async def test_borrowed_health_pool_remains_owned_by_caller(tmp_path):
    engine = db.create_db_engine(tmp_path / "borrowed.db")
    pool = engine.pool
    try:
        assert (await db.check_db_health(engine))["status"] == "ok"
        assert engine.pool is pool
        assert engine.pool.checkedin() == 1
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT 42"))).scalar_one() == 42
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_private_health_pool_disposed_when_connect_fails(tmp_path, monkeypatch):
    parent = tmp_path / "blocked"
    engine = db.create_db_engine(parent / "health.db")
    pool = engine.pool
    parent.rmdir()
    parent.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(db, "create_db_engine", lambda: engine)
    try:
        with pytest.raises(OperationalError):
            await db.check_db_health()
        assert engine.pool is not pool
    finally:
        await engine.dispose()


def test_http_health_reuses_runtime_pool_and_shutdown_releases_database(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import current_product_state, reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings

    path = tmp_path / "http-health.db"
    monkeypatch.setenv("MATHTUTOR_DB_PATH", str(path))
    monkeypatch.setenv("MATHTUTOR_DATA_ROOT", str(tmp_path))
    reset_product_state()
    app = create_math_tutor_app(
        MathTutorSecuritySettings(environment="test", host="127.0.0.1"),
        auth_enabled=False,
        db_path=str(path),
    )
    state = current_product_state()
    retained = []
    create_engine = db.create_db_engine

    def record_new_engine(*args, **kwargs):
        engine = create_engine(*args, **kwargs)
        retained.append(engine)
        return engine

    monkeypatch.setattr(db, "create_db_engine", record_new_engine)
    try:
        with TestClient(app) as client:
            for _ in range(3):
                response = client.get("/health")
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
            assert not retained
            assert state.uow.engine.pool.checkedin() > 0
        assert state.lifecycle_status == "STOPPED"
        assert not Path(f"{path}-wal").exists()
        assert not Path(f"{path}-shm").exists()
    finally:
        reset_product_state()

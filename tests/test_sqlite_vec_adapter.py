"""Optional sqlite-vec adapter contracts, independent of the retired retrieval stack."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mathtutor.infrastructure.sqlite_vec_index import (
    SqliteVecUnavailableError,
    SqliteVecVectorIndex,
)
from mathtutor.repositories.document_repository import cosine_similarity

pytestmark = pytest.mark.asyncio
_PROBE_DYLIB = Path("/tmp/sqlite_vec_probe/extracted/sqlite_vec/vec0.dylib")
requires_sqlite_vec = pytest.mark.skipif(
    not _PROBE_DYLIB.exists(),
    reason="optional sqlite-vec probe library is absent",
)


def test_sqlite_vec_unavailable_path_degrades_cleanly():
    """sqlite-vec 不可用（扩展路径不存在/不可加载）→ 构造 fail-closed、
    try_open 干净返回 None、probe 返回 False —— 绝不崩溃。"""
    bogus = "/tmp/does/not/exist/sqlite_vec_missing.dylib"
    with pytest.raises(SqliteVecUnavailableError):
        SqliteVecVectorIndex(bogus, dimension=4)
    assert SqliteVecVectorIndex.try_open(bogus, dimension=4) is None
    assert SqliteVecVectorIndex.probe(bogus) is False


@requires_sqlite_vec
async def test_sqlite_vec_rejects_invalid_entries():
    """维度不匹配/非有限值/重复标识 → ValueError（fail-closed，与
    validate_vector 同一纪律）。"""
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    with pytest.raises(ValueError):
        await index.build([("a", (0.1, 0.2, 0.3))])  # 维度 3 ≠ 4
    with pytest.raises(ValueError):
        await index.build([("a", (0.1, float("nan"), 0.3, 0.4))])
    with pytest.raises(ValueError):
        await index.build([("a", (1.0, 0.0, 0.0, 0.0)), ("a", (0.0, 1.0, 0.0, 0.0))])
    index.close()


@requires_sqlite_vec
async def test_sqlite_vec_probe_and_version():
    """探测产物在本 Python 上真实可加载（第二轮实测的回归钉）。"""
    assert SqliteVecVectorIndex.probe(str(_PROBE_DYLIB)) is True
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    assert index.extension_version().startswith("v")
    assert index.indexed_count() == 0
    index.close()


@requires_sqlite_vec
async def test_sqlite_vec_search_matches_full_scan_cosine():
    """vec0 KNN 排序与 full-scan cosine 排序一致（相似度数值容差内相等）
    —— 证明可选 ANN 路径与既有 full-scan fusion 契约可互换。"""
    # 契约：向量为 L2-normalized（descriptor.normalization="l2"）；
    # 全量扫描参照用点积（normalized 时点积 == 余弦）。
    entries = [
        ("zero", (1.0, 0.0, 0.0, 0.0)),
        ("one", (0.0, 1.0, 0.0, 0.0)),
        ("diag", (0.7071067811865476, 0.7071067811865476, 0.0, 0.0)),
        ("neg", (-1.0, 0.0, 0.0, 0.0)),
    ]
    query = (0.6, 0.8, 0.0, 0.0)  # |query| = 1.0
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    assert await index.build(entries) == 4
    hits = await index.search(query, k=4)

    expected = sorted(
        (
            entry_id,
            max(-1.0, min(1.0, cosine_similarity(query, vector))),
        )
        for entry_id, vector in entries
    )
    expected.sort(key=lambda row: row[1], reverse=True)
    assert [hit.id for hit in hits] == [entry_id for entry_id, _ in expected]
    for hit, (_, wanted) in zip(hits, expected):
        assert abs(hit.similarity - wanted) < 1e-5
    index.close()


@requires_sqlite_vec
async def test_sqlite_vec_rebuild_replaces_entries_and_empty_search():
    """build 是整体替换（derived projection，绝不追加）；空索引/非正 k
    搜索返回空列表。"""
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    await index.build(
        [("old-1", (1.0, 0.0, 0.0, 0.0)), ("old-2", (0.0, 1.0, 0.0, 0.0))]
    )
    assert await index.search((1.0, 0.0, 0.0, 0.0), k=0) == []
    assert await index.search((1.0, 0.0, 0.0, 0.0), k=-1) == []

    await index.build([("new-1", (0.0, 0.0, 1.0, 0.0))])
    assert index.indexed_count() == 1
    hits = await index.search((0.0, 0.0, 1.0, 0.0), k=10)
    assert [hit.id for hit in hits] == ["new-1"]  # 旧条目已被整体替换
    assert abs(hits[0].similarity - 1.0) < 1e-5
    index.close()


# Capability fakes keep these regressions independent of the host OS/SQLite build.
class _ConnectionWithoutExtensionLoading:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _ExtensionConnection(_ConnectionWithoutExtensionLoading):
    def __init__(
        self,
        *,
        load_error=None,
        enable_error=None,
        version_error=None,
        disable_error=None,
    ):
        super().__init__()
        self.load_error = load_error
        self.enable_error = enable_error
        self.version_error = version_error
        self.disable_error = disable_error
        self.enabled = []

    def enable_load_extension(self, enabled):
        self.enabled.append(enabled)
        error = self.enable_error if enabled else self.disable_error
        if error is not None:
            raise error

    def load_extension(self, extension_path):
        if self.load_error is not None:
            raise self.load_error

    def execute(self, query):
        if self.version_error is not None:
            raise self.version_error
        return self

    def fetchone(self):
        return ("v0.1.9",)


def _use_connection(monkeypatch, conn):
    monkeypatch.setattr(
        "mathtutor.infrastructure.sqlite_vec_index.sqlite3.connect", lambda _: conn
    )


async def test_sqlite_vec_missing_extension_path_degrades(tmp_path):
    path = str(tmp_path / "sqlite_vec_missing.dylib")
    with pytest.raises(SqliteVecUnavailableError):
        SqliteVecVectorIndex(path, dimension=4)


@pytest.mark.parametrize("non_callable", [False, True])
async def test_sqlite_vec_runtime_without_extension_loading_degrades(
    monkeypatch, non_callable
):
    conn = _ConnectionWithoutExtensionLoading()
    if non_callable:
        conn.enable_load_extension = None
    _use_connection(monkeypatch, conn)
    with pytest.raises(
        SqliteVecUnavailableError,
        match="SQLite extension loading is not supported by this runtime",
    ):
        SqliteVecVectorIndex("optional-extension", dimension=4)
    assert conn.closed


@pytest.mark.parametrize(
    "error_type", [AttributeError, OSError, sqlite3.OperationalError]
)
async def test_sqlite_vec_load_extension_failure_degrades(monkeypatch, error_type):
    error = error_type("extension cannot be loaded")
    conn = _ExtensionConnection(load_error=error)
    _use_connection(monkeypatch, conn)
    with pytest.raises(SqliteVecUnavailableError) as caught:
        SqliteVecVectorIndex("optional-extension", dimension=4)
    assert caught.value.__cause__ is error
    assert conn.enabled == [True, False]
    assert conn.closed


async def test_sqlite_vec_try_open_returns_none_when_unavailable(monkeypatch):
    conn = _ConnectionWithoutExtensionLoading()
    _use_connection(monkeypatch, conn)
    assert SqliteVecVectorIndex.try_open("optional-extension", dimension=4) is None
    assert conn.closed


async def test_sqlite_vec_probe_returns_false_when_unavailable(monkeypatch):
    conn = _ConnectionWithoutExtensionLoading()
    _use_connection(monkeypatch, conn)
    assert SqliteVecVectorIndex.probe("optional-extension") is False
    assert conn.closed


@pytest.mark.parametrize("stage", ["enable", "version", "disable"])
async def test_sqlite_vec_initialization_failure_closes_connection(monkeypatch, stage):
    conn = _ExtensionConnection(
        **{f"{stage}_error": sqlite3.OperationalError("capability unavailable")}
    )
    _use_connection(monkeypatch, conn)
    with pytest.raises(SqliteVecUnavailableError):
        SqliteVecVectorIndex("optional-extension", dimension=4)
    assert conn.closed
    assert conn.enabled == [True, False]


async def test_sqlite_vec_loading_is_disabled_after_success(monkeypatch):
    conn = _ExtensionConnection()
    _use_connection(monkeypatch, conn)
    index = SqliteVecVectorIndex("optional-extension", dimension=4)
    assert index.extension_version() == "v0.1.9"
    assert conn.enabled == [True, False]
    assert not conn.closed
    index.close()
    assert conn.closed


@pytest.mark.parametrize("entrypoint", ["constructor", "try_open", "probe"])
async def test_sqlite_vec_programmer_errors_are_not_swallowed(monkeypatch, entrypoint):
    conn = _ExtensionConnection(version_error=TypeError("programmer error"))
    _use_connection(monkeypatch, conn)
    with pytest.raises(TypeError, match="programmer error"):
        if entrypoint == "probe":
            SqliteVecVectorIndex.probe("optional-extension")
        elif entrypoint == "try_open":
            SqliteVecVectorIndex.try_open("optional-extension", dimension=4)
        else:
            SqliteVecVectorIndex("optional-extension", dimension=4)
    assert conn.closed


async def test_sqlite_vec_invalid_dimension_is_not_unavailable():
    with pytest.raises(ValueError, match="dimension"):
        SqliteVecVectorIndex.try_open("optional-extension", dimension=0)

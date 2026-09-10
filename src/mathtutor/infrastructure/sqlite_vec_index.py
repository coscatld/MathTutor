"""SqliteVecVectorIndex — optional sqlite-vec ANN adapter (Phase 6 第二轮).

**这是可选 adapter，绝不进入生产默认接线。** 本模块的存在前提是
2026-08-21 的第二轮实测（docs/PHASE6_SQLITE_VEC_EVALUATION.md）：
sqlite-vec 0.1.9 的 macOS arm64 dylib 在本机 Python 3.11 / SQLite
3.53.2 上 ``load_extension`` + ``vec_version()`` + vec0 KNN 全链路
实测通过。产品默认路径（ProductState / product_app / 检索仓库）**不
引用本模块**；未来若接入，由接线层显式传入扩展路径构造。

定位：检索链（INVARIANT C）中「metadata filter → lexical/vector
candidate retrieval → optional reranking」的 vector candidate 段的可
选 ANN 实现。它只做一件事 —— 把调用方在 **metadata 过滤之后** 传入的
(标识, 向量) 集合建成 vec0 虚拟表并回答 top-k 近邻。它不持有 owner /
retrieval_enabled / stage 等任何过滤逻辑（过滤永远在数据层/仓库层），
因此永远不可能绕过 INVARIANT D/F 的数据层阻断。

契约对齐（与 DocumentRepository 检索契约一致）：

- ``build(entries)`` 对应 ``replace_vectors`` 的派生投影语义：整体
  替换、绝不追加（INVARIANT E：向量索引是 derived projection，换模型
  时 chunks→rebuild，不重新导入用户原文件 —— 本类只消费调用方给的
  向量，从不读文件）；
- ``search(query, k)`` 返回 (标识, 余弦相似度)，供调用方与词法分做
  ``fuse_retrieval_scores`` 融合；相似度换算与
  :func:`mathtutor.repositories.document_repository
  .cosine_similarity` 同源（vec0 cosine 距离 = 1 − 余弦，clamp 到
  [-1, 1]）；
- 索引存放于本实例私有的 :memory: 连接，与产品库（短事务/WAL）零
  交互；构造时扩展加载失败 → 抛 :class:`SqliteVecUnavailableError`
  （fail-closed），配合 :meth:`try_open` 实现「sqlite-vec 不可用 →
  干净 DEGRADED」的可选接线。

不安装、不依赖 ``sqlite_vec`` Python 包：直接 ``load_extension`` 调用
方传入的 .dylib/.so 路径（评估 artifact 形态；正式接入时的分发方式
属于 Embedding Distribution Strategy —— 仍 DEFERRED）。
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from typing import Sequence

from mathtutor.domain.embedding import EmbeddingVector

# vec0 虚拟表名（实例私有 :memory: 连接内，常量即可）。
_VEC_TABLE = "mt_vec_items"


class SqliteVecUnavailableError(RuntimeError):
    """sqlite-vec 扩展加载失败（可选路径的 fail-closed 异常）。

    调用方应捕获本异常（或使用 :meth:`SqliteVecVectorIndex.try_open`）
    并降级到 full-scan vector fusion / 纯词法 —— 绝不因 sqlite-vec
    缺席而影响产品启动或检索可用性。
    """


@dataclass(frozen=True, slots=True)
class VectorHit:
    """一条 ANN 命中：标识 + 余弦相似度 + 原始 vec0 距离（调试用）。"""

    id: str
    similarity: float  # 1 - cosine distance, clamped [-1, 1]
    distance: float  # vec0 cosine distance (raw)


class SqliteVecVectorIndex:
    """可选 sqlite-vec 向量索引适配器（构造时显式传入扩展路径）。

    - 构造即加载：:class:`sqlite3.Connection` 私有、``enable_load_extension``
      → ``load_extension`` → ``vec_version()`` 全链路在构造时验证，
      失败抛 :class:`SqliteVecUnavailableError`；
    - 同步 SQLite 调用封装在 async 方法里（:memory: 上的 vec0 操作是
      亚毫秒级纯 CPU 工作，与 InMemoryDocumentRepository 的 async 内联
      风格一致）；
    - 向量以 JSON 文本写入 vec0 表（与 document_chunk_vectors 的 JSON
      列同一序列化形态），rowid ↔ 标识映射由本类维护。
    """

    def __init__(self, extension_path: str, *, dimension: int) -> None:
        if dimension < 1:
            raise ValueError(f"vector dimension must be >= 1, got {dimension}")
        self._dimension = dimension
        self._extension_path = extension_path
        self._ids: list[str] = []
        self._conn = self._open_connection(extension_path)
        try:
            self._version = self._read_version()
        except BaseException:
            # Cleanup must also run for programmer errors, which still propagate.
            _close_failed_connection(self._conn)
            raise

    # -------------------------------------------------------- lifecycle

    def _open_connection(self, extension_path: str) -> sqlite3.Connection:
        conn = None
        ready = False
        try:
            conn = sqlite3.connect(":memory:")
            enable = getattr(conn, "enable_load_extension", None)
            if not callable(enable):
                raise SqliteVecUnavailableError(
                    "SQLite extension loading is not supported by this runtime"
                )
            loaded = False
            try:
                enable(True)
                conn.load_extension(extension_path)
                loaded = True
            finally:
                try:
                    enable(False)
                except (AttributeError, sqlite3.Error, OSError):
                    # Preserve the original loading error. If loading succeeded,
                    # inability to disable loading makes this connection unusable.
                    if loaded:
                        raise
            ready = True
            return conn
        except (AttributeError, sqlite3.Error, OSError) as error:
            raise SqliteVecUnavailableError(
                f"sqlite-vec 扩展加载失败（path={extension_path!r}）：{error}"
            ) from error
        finally:
            if conn is not None and not ready:
                _close_failed_connection(conn)

    def _read_version(self) -> str:
        try:
            row = self._conn.execute("select vec_version()").fetchone()
            if not row or not isinstance(row[0], str) or not row[0].strip():
                raise SqliteVecUnavailableError("vec_version() returned no valid version")
            return row[0]
        except (AttributeError, sqlite3.Error, OSError) as error:
            raise SqliteVecUnavailableError(
                f"vec_version() 查询失败（扩展可能不兼容）：{error}"
            ) from error

    def close(self) -> None:
        self._conn.close()

    def extension_version(self) -> str:
        """加载到的 sqlite-vec 版本串（如 ``v0.1.9``）。"""
        return self._version

    def indexed_count(self) -> int:
        """当前索引内条目数（未 build 时为 0）。"""
        return len(self._ids)

    # ------------------------------------------------------------ build

    async def build(self, entries: Sequence[tuple[str, EmbeddingVector]]) -> int:
        """整体重建 vec0 索引（derived projection：替换，绝不追加）。

        ``entries`` 为 (标识, 向量) 序列：标识必须唯一；向量维度必须
        等于构造时声明的 ``dimension`` 且全为有限值 —— 任一违规直接
        ValueError（fail-closed，与 :func:`validate_vector` 同一纪律）。
        返回入库条数。
        """
        _rebuild_vec_table(self._conn, self._dimension)
        seen: set[str] = set()
        rows: list[tuple[int, str]] = []
        for index, (entry_id, vector) in enumerate(entries, start=1):
            if entry_id in seen:
                raise ValueError(f"duplicate vector entry id: {entry_id!r}")
            seen.add(entry_id)
            _validate_entry_vector(vector, self._dimension, entry_id)
            rows.append((index, json.dumps(list(vector))))
        self._conn.executemany(
            f"insert into {_VEC_TABLE}(rowid, embedding) values (?, ?)", rows
        )
        self._ids = [entry_id for entry_id, _ in entries]
        return len(self._ids)

    # ----------------------------------------------------------- search

    async def search(self, query: EmbeddingVector, k: int) -> list[VectorHit]:
        """Top-k 近邻（余弦距离）；空索引/非正 k 返回空列表。"""
        if k <= 0 or not self._ids:
            return []
        _validate_entry_vector(query, self._dimension, "<query>")
        rows = self._conn.execute(
            f"select rowid, distance from {_VEC_TABLE} "
            f"where embedding match ? and k = {int(k)} order by distance",
            (json.dumps(list(query)),),
        ).fetchall()
        hits: list[VectorHit] = []
        for rowid, distance in rows:
            similarity = max(-1.0, min(1.0, 1.0 - float(distance)))
            hits.append(
                VectorHit(id=self._ids[int(rowid) - 1], similarity=similarity, distance=float(distance))
            )
        return hits

    # ---------------------------------------------------------- helpers

    @classmethod
    def probe(cls, extension_path: str) -> bool:
        """一次性扩展加载探测（ops/测试用）：能 load + vec_version 即 True。"""
        try:
            index = cls(extension_path, dimension=1)
            index.close()
            return True
        except SqliteVecUnavailableError:
            return False

    @classmethod
    def try_open(cls, extension_path: str, *, dimension: int) -> "SqliteVecVectorIndex | None":
        """可选能力不可用时返回 None；参数错误和编程错误仍向上传播。"""
        try:
            return cls(extension_path, dimension=dimension)
        except SqliteVecUnavailableError:
            return None


def _close_failed_connection(conn: sqlite3.Connection) -> None:
    """Best-effort cleanup without replacing the initialization failure."""
    with suppress(AttributeError, sqlite3.Error, OSError):
        conn.close()


def _validate_entry_vector(vector: EmbeddingVector, dimension: int, entry_id: str) -> None:
    """维度 + 有限值检查；违规抛 ValueError（fail-closed）。"""
    if len(vector) != dimension:
        raise ValueError(
            f"vector dimension mismatch for {entry_id!r}: expected {dimension}, "
            f"got {len(vector)}"
        )
    for value in vector:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"vector for {entry_id!r} contains a non-finite value")


def _rebuild_vec_table(conn: sqlite3.Connection, dimension: int) -> None:
    """整体替换 vec0 表（drop + create，维度已由构造校验）。"""
    conn.execute(f"drop table if exists {_VEC_TABLE}")
    conn.execute(
        f"create virtual table {_VEC_TABLE} using vec0("
        f"embedding float[{int(dimension)}] distance_metric=cosine)"
    )


__all__ = [
    "SqliteVecUnavailableError",
    "SqliteVecVectorIndex",
    "VectorHit",
]

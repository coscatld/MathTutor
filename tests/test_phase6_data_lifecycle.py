"""Phase 6 round 2 — data lifecycle / privacy / export (SUBAGENT D).

Covers the twelve spec items:

 1. five-category classification covers EVERY business table; sensitive
    fields classify SECRET;
 2. delete_document keeps the status-quo soft-delete semantics and makes
    chunk + storage-file cleanup REAL;
 3. delete_personal_memory keeps the PersonalMemoryService semantics;
 4. purge_user_documents wipes one student's documents/chunks/files and
    never touches another student;
 5. purge_personal_memory wipes one student's memory nodes;
 6. rebuild_derived_indexes rebuilds from chunk facts (deterministic fake
    backend); no backend → honest ``unavailable``, never raises or fakes;
 7. delete_educational_history deletes result facts then REPLAYS the
    projection from remaining evidence (never a hardcoded value write —
    plus a static assertion over the module source);
 8. delete_educational_history is idempotent;
 9. educational-history deletion ≠ Memory CRUD (both directions);
10. export carries whitelist fields only; attestation/reasoning/secret/
    payload/storage-path/hash fields are absent;
11. lifecycle/export logs go through sanitization (no plaintext);
12. no trash semantics (immediately invisible) and no new tables/migrations.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from mathtutor.application.data_export import (
    EXPORT_ALLOWED_FIELDS,
    ExportValidationError,
    build_student_export,
    validate_export,
)
from mathtutor.application.data_lifecycle import (
    CATEGORY_AUTHORITY_EDUCATIONAL,
    CATEGORY_DERIVED,
    CATEGORY_SECRET,
    CATEGORY_SYSTEM,
    CATEGORY_USER_CONTROLLED,
    DATA_CATEGORIES,
    DataLifecycleService,
    classify_field,
    classify_table,
    sanitize_summary,
)
from mathtutor.application.document_ingestion import (
    DocumentIndexManager,
    DocumentIngestionService,
)
from mathtutor.application.personal_memory_service import (
    PersonalMemoryService,
)
from mathtutor.domain.documents import DocumentChunk, UserDocument
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.infrastructure.embedding_runtime import (
    EmbeddingRuntime,
    FakeEmbeddingBackend,
)
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure.schema import (
    attempt_assessments,
    attempt_submissions,
    attempts,
    document_index_builds,
    mastery_evidence,
    misconception_observations,
    tutoring_cycles,
    verification_logs,
)
from mathtutor.learning.projection import project_student_state
from mathtutor.repositories import sqlite_education
from mathtutor.repositories.sqlite_knowledge import (
    SQLiteDocumentRepository,
    SQLiteMemoryRepository,
)
from mathtutor.repositories.sqlite_runtime import (
    create_cycle,
    ensure_student,
)
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.security.scopes import student_uuid

pytestmark = pytest.mark.asyncio

_SEED_BODY = "二次方程求根公式 x = (-b ± sqrt(b^2 - 4ac)) / (2a)"


def _sid() -> str:
    return str(uuid4())


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest_asyncio.fixture()
async def env(tmp_path):
    db_file = tmp_path / "math_tutor.db"
    upgrade_db(str(db_file))
    engine = create_db_engine(db_file)
    uow = MathTutorUow(engine)
    document_repository = SQLiteDocumentRepository(engine)
    memory_repository = SQLiteMemoryRepository(engine)
    storage = DocumentStorage(tmp_path / "data")
    documents = DocumentIngestionService(
        repository=document_repository, storage=storage
    )
    memory_service = PersonalMemoryService(memory_repository)
    runtime = EmbeddingRuntime(FakeEmbeddingBackend())
    index_manager = DocumentIndexManager(
        repository=document_repository, embedding_runtime=runtime
    )
    lifecycle = DataLifecycleService(
        documents=documents,
        document_repository=document_repository,
        storage=storage,
        memory=memory_service,
        index_manager=index_manager,
        uow=uow,
    )
    yield SimpleNamespace(
        db_file=db_file,
        engine=engine,
        uow=uow,
        document_repository=document_repository,
        memory_repository=memory_repository,
        storage=storage,
        documents=documents,
        memory=memory_service,
        runtime=runtime,
        index_manager=index_manager,
        lifecycle=lifecycle,
    )
    await engine.dispose()


async def _seed_document(
    repo, storage, student_id: str, *, filename: str = "notes.txt", body: str = _SEED_BODY
) -> UserDocument:
    """One ready document with a stored file and one chunk fact (no parser)."""
    doc = UserDocument(
        student_id=student_uuid(student_id),
        filename=filename,
        mime_type="text/plain",
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        storage_ref=storage.ref_for(student_uuid(student_id), uuid4(), filename),
        status="ready",
        size_bytes=len(body.encode("utf-8")),
        parser_version="mt-parser-v1",
    )
    stored = await repo.add_document(student_id, doc)
    await storage.store_bytes(doc.storage_ref, body.encode("utf-8"))
    await repo.replace_chunks(
        student_id,
        doc.document_id,
        [
            DocumentChunk(
                document_id=doc.document_id,
                student_id=student_uuid(student_id),
                sequence=0,
                page=None,
                section="",
                text=body,
                content_hash=_chunk_hash(body),
                metadata_json={},
                chunker_version="mt-chunker-v1",
            )
        ],
    )
    return stored


async def _seed_education(
    uow: MathTutorUow, student_id: str, *, attempts: int = 2
) -> dict:
    """Session + cycle + attempts/assessments/evidence/observations +
    replayed projection — built ONLY from existing repository functions."""
    from mathtutor.infrastructure.schema import (
        math_problems,
        solution_candidates,
    )

    async with uow.transaction() as conn:
        await ensure_student(conn, student_id=student_id)
        snapshot = await create_cycle(
            conn, student_id=student_id, client_session_id="seed"
        )
        problem_id = uuid4()
        await conn.execute(
            math_problems.insert().values(
                problem_id=str(problem_id),
                schema_version="mt-problem-v1",
                canonicalization_version="1",
                problem_type="linear",  # stable MVP family → LINEAR_EQUATION skill
                normalized_ast={},
                display_latex="2x + 3 = 7",
                content_hash=f"seed-problem-{problem_id}",
            )
        )
        candidate_id = uuid4()
        await conn.execute(
            solution_candidates.insert().values(
                candidate_id=str(candidate_id),
                problem_id=str(problem_id),
                steps=[],
                final_answer={},
                payload_hash=f"seed-candidate-{candidate_id}",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        # Candidate-linked verification log — CONTENT authority, must survive.
        reference_log_id = str(uuid4())
        await conn.execute(
            verification_logs.insert().values(
                log_id=reference_log_id,
                candidate_id=str(candidate_id),
                attempt_id=None,
                problem_id=str(problem_id),
                verdict="verified",
                checks=[],
                attestation_hash="CAND-ATTEST-MARKER",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        attempt_ids: list[UUID] = []
        for index in range(attempts):
            submission_id = await sqlite_education.insert_attempt_submission(
                conn,
                student_id=student_id,
                cycle_id=snapshot.cycle_id,
                raw_text=f"RAW-ANSWER-MARKER-{index}",
                idempotency_key=f"seed-submission-{index}",
            )
            attempt_id = await sqlite_education.insert_attempt(
                conn,
                student_id=student_id,
                cycle_id=snapshot.cycle_id,
                attempt_submission_id=submission_id,
                parsed_steps=[],
                attempt_index=index + 1,
                payload_hash=f"seed-attempt-{index}",
            )
            attempt_ids.append(attempt_id)
            log_id = await sqlite_education.insert_attempt_assessment(
                conn,
                student_id=student_id,
                attempt_id=attempt_id,
                cycle_id=snapshot.cycle_id,
                problem_id=problem_id,
                reference_solution_log_id=UUID(reference_log_id),
                correctness="correct",
                score=1.0,
                attestation_hash=f"ATT-MARK-{index}",
            )
            await sqlite_education.insert_mastery_evidence(
                conn,
                student_id=student_id,
                attempt_assessment_log_id=log_id,
                correctness="correct",
                score=1.0,
                difficulty=2,
                effective_assistance_level=1,
                evidence_version="mt-evidence-v1",
                # mastery_evidence.idempotency_key is GLOBALLY unique —
                # namespace per student so two seeded students never collide.
                idempotency_key=f"seed-evidence-{student_id[:12]}-{index}",
            )
            await sqlite_education.insert_misconception_observation(
                conn,
                student_id=student_id,
                attempt_id=attempt_id,
                rule_id=f"mt-rule-seed-{index}",
                confidence=0.8,
                detail={"skill_id": "LINEAR_EQUATION"},
            )
        evidence = await sqlite_education.load_evidence_for_student(conn, student_id)
        observations = await sqlite_education.load_misconception_observations_for_student(
            conn, student_id
        )
        replay = project_student_state(
            student_id=student_uuid(student_id),
            evidence=evidence,
            observations=observations,
        )
        await sqlite_education.upsert_student_state(
            conn,
            student_id=student_id,
            estimator_version=replay.estimator_version,
            projection_version=replay.projection_version,
            concept_mastery=list(replay.concept_mastery),
            skill_mastery=list(replay.skill_mastery),
            active_misconceptions=list(replay.active_misconceptions),
        )
        return {
            "cycle_id": snapshot.cycle_id,
            "problem_id": problem_id,
            "candidate_id": candidate_id,
            "reference_log_id": reference_log_id,
            "attempt_ids": attempt_ids,
            "attempt_count": attempts,
        }


async def _count(env, table) -> int:
    async with env.uow.transaction() as conn:
        return int(
            (await conn.execute(select(func.count()).select_from(table))).scalar() or 0
        )


def _projection_key(projection: dict | None) -> tuple:
    """Stable projection fields (excludes updated_at, which changes on write)."""
    assert projection is not None
    return (
        projection["estimator_version"],
        projection["projection_version"],
        projection["skill_mastery"],
        projection["concept_mastery"],
        projection["active_misconceptions"],
    )


# ---------------------------------------------------------------------------
# 1. Five-category classification — full coverage + SECRET field classes.
# ---------------------------------------------------------------------------


def test_classification_covers_every_business_table() -> None:
    """Every business table in the schema has a category; no unclassified
    table and no classified ghost (both directions asserted)."""
    from mathtutor.infrastructure.schema import metadata
    from mathtutor.learning.knowledge_tracing.schema import metadata as tracking_metadata

    tables = set(metadata.tables) | set(tracking_metadata.tables)
    assert tables == set(DATA_CATEGORIES)
    for name in tables:
        assert classify_table(name) in {
            CATEGORY_AUTHORITY_EDUCATIONAL,
            CATEGORY_USER_CONTROLLED,
            CATEGORY_DERIVED,
            CATEGORY_SYSTEM,
        }, name


def test_classify_table_unknown_raises() -> None:
    with pytest.raises(ValueError):
        classify_table("nonexistent_table")


def test_sensitive_fields_classified_secret() -> None:
    """Credential + attestation/reasoning/trace/payload/raw-text/path/hash/
    vector fields are explicitly SECRET (never exported, never logged)."""
    for table, field in (
        ("attempt_assessments", "attestation_hash"),
        ("verification_logs", "attestation_hash"),
        ("problem_submissions", "raw_text"),
        ("attempt_submissions", "raw_text"),
        ("domain_outbox", "payload"),
        ("attempts", "payload_hash"),
        ("attempts", "parsed_steps"),
        ("user_documents", "storage_ref"),
        ("user_documents", "content_hash"),
        ("document_chunks", "text"),
        ("document_chunk_vectors", "vector"),
        ("verification_logs", "checks"),
        ("misconception_observations", "detail"),
        ("solution_candidates", "steps"),
        ("cycle_transitions", "chosen_action"),
        # 字段分类是名字驱动的：任何现有表上的凭据类字段名都按规则判 SECRET
        # （真实 API key 在库外的 OS SecretStore；库内一旦出现凭据列即被规则覆盖）。
        ("users", "api_key"),
    ):
        assert classify_field(table, field) == CATEGORY_SECRET, (table, field)
    assert classify_field("user_documents", "filename") is None
    assert classify_field("personal_memory_nodes", "memory_type") is None
    assert classify_field("user_documents", "status") is None
    with pytest.raises(ValueError):
        classify_field("nonexistent_table", "any_field")


def test_classification_spot_checks() -> None:
    assert classify_table("user_documents") == CATEGORY_USER_CONTROLLED
    assert classify_table("document_chunks") == CATEGORY_USER_CONTROLLED
    assert classify_table("personal_memory_nodes") == CATEGORY_USER_CONTROLLED
    assert classify_table("mastery_evidence") == CATEGORY_AUTHORITY_EDUCATIONAL
    assert classify_table("attempts") == CATEGORY_AUTHORITY_EDUCATIONAL
    assert classify_table("student_state_projections") == CATEGORY_DERIVED
    assert classify_table("document_chunk_vectors") == CATEGORY_DERIVED
    assert classify_table("tutoring_cycles") == CATEGORY_SYSTEM
    assert classify_table("domain_outbox") == CATEGORY_SYSTEM


# ---------------------------------------------------------------------------
# 2. delete_document — status-quo soft delete + REAL chunk/file cleanup.
# ---------------------------------------------------------------------------


async def test_delete_document_soft_delete_and_real_cleanup(env) -> None:
    sid, other = _sid(), _sid()
    doc = await _seed_document(env.document_repository, env.storage, sid)
    await env.index_manager.build_index(sid, doc.document_id)  # seed vectors+build row
    other_doc = await _seed_document(
        env.document_repository, env.storage, other, filename="other.txt"
    )
    assert await env.storage.exists(doc.storage_ref) is True

    assert await env.lifecycle.delete_document(sid, doc.document_id) is True

    # 现状语义：立即不可见（无回收站）；行仍在，deleted_at 已置。
    assert await env.document_repository.get_document(sid, doc.document_id) is None
    tombstone = await env.document_repository.get_document(
        sid, doc.document_id, include_deleted=True
    )
    assert tombstone is not None and tombstone.deleted_at is not None
    # chunks / 派生向量 / index 构建行真实清理。
    assert await env.document_repository.list_chunks(sid, doc.document_id) == []
    assert await env.document_repository.get_vectors(sid, doc.document_id) == {}
    async with env.uow.transaction() as conn:
        builds = (
            await conn.execute(
                select(func.count()).select_from(document_index_builds).where(
                    document_index_builds.c.student_id == sid
                )
            )
        ).scalar()
    assert int(builds or 0) == 0
    # 存储文件物理删除真实发生。
    assert await env.storage.exists(doc.storage_ref) is False
    # 无回收站语义：重复删除返回 False，行依旧不可见。
    assert await env.lifecycle.delete_document(sid, doc.document_id) is False
    # 其他学生数据不受影响。
    assert await env.document_repository.get_document(other, other_doc.document_id) is not None
    assert len(await env.document_repository.list_chunks(other, other_doc.document_id)) == 1
    assert await env.storage.exists(other_doc.storage_ref) is True


# ---------------------------------------------------------------------------
# 3. delete_personal_memory — PersonalMemoryService semantics verbatim.
# ---------------------------------------------------------------------------


async def test_delete_personal_memory_status_quo_semantics(env) -> None:
    sid = _sid()
    node = await env.memory.add_explicit(
        sid,
        memory_type="user_note",
        subject="目标",
        predicate="wants",
        object_json={"goal": "期末 95 分"},
    )
    assert await env.lifecycle.delete_personal_memory(sid, node.memory_id) is True
    assert await env.memory_repository.get_node(sid, node.memory_id) is None
    tombstone = await env.memory_repository.get_node(
        sid, node.memory_id, include_deleted=True
    )
    assert tombstone is not None and tombstone.deleted_at is not None
    # 无回收站语义。
    assert await env.lifecycle.delete_personal_memory(sid, node.memory_id) is False


# ---------------------------------------------------------------------------
# 4/5. purge — whole-student wipe, other students untouched.
# ---------------------------------------------------------------------------


async def test_purge_user_documents_full_wipe_other_student_untouched(env) -> None:
    sid, other = _sid(), _sid()
    live_doc = await _seed_document(env.document_repository, env.storage, sid)
    # A document soft-deleted by the OLD path (chunks + file left behind).
    # Different body: user_documents has a unique (student_id, content_hash).
    stale_doc = await _seed_document(
        env.document_repository,
        env.storage,
        sid,
        filename="stale.txt",
        body="旧文档正文 OLD-STALE-BODY",
    )
    await env.document_repository.soft_delete_document(sid, stale_doc.document_id)
    other_doc = await _seed_document(
        env.document_repository, env.storage, other, filename="other.txt"
    )

    summary = await env.lifecycle.purge_user_documents(sid)

    assert summary["documents_soft_deleted"] == 1  # only the live row flips
    assert summary["chunks_removed"] == 2  # live + stale chunks
    assert summary["storage_files_removed"] == 2
    for doc in (live_doc, stale_doc):
        assert await env.document_repository.get_document(sid, doc.document_id) is None
        assert await env.document_repository.list_chunks(sid, doc.document_id) == []
        assert await env.storage.exists(doc.storage_ref) is False
    tombstones = await env.document_repository.list_documents(
        sid, include_deleted=True
    )
    assert len(tombstones) == 2
    assert all(d.deleted_at is not None for d in tombstones)
    # 其他学生完好。
    assert await env.document_repository.get_document(other, other_doc.document_id) is not None
    assert len(await env.document_repository.list_chunks(other, other_doc.document_id)) == 1
    assert await env.storage.exists(other_doc.storage_ref) is True


async def test_purge_personal_memory_full_wipe_other_student_untouched(env) -> None:
    sid, other = _sid(), _sid()
    for index in range(2):
        await env.memory.add_explicit(
            sid,
            memory_type="user_note",
            subject=f"笔记{index}",
            predicate="says",
            object_json={"text": f"内容{index}"},
        )
    other_node = await env.memory.add_explicit(
        other,
        memory_type="learning_goal",
        subject="目标",
        predicate="wants",
        object_json={"goal": "保持"},
    )

    summary = await env.lifecycle.purge_personal_memory(sid)

    assert summary["memories_soft_deleted"] == 2
    assert await env.memory_repository.list_nodes(sid) == []
    tombstones = await env.memory_repository.list_nodes(sid, include_deleted=True)
    assert len(tombstones) == 2
    assert all(node.deleted_at is not None for node in tombstones)
    live_other = await env.memory_repository.list_nodes(other)
    assert [node.memory_id for node in live_other] == [other_node.memory_id]


# ---------------------------------------------------------------------------
# 6. rebuild_derived_indexes — from chunk FACTS; honest ``unavailable``.
# ---------------------------------------------------------------------------


async def test_rebuild_derived_indexes_from_chunks_fake_backend(env) -> None:
    sid = _sid()
    doc = await _seed_document(env.document_repository, env.storage, sid)
    await env.index_manager.build_index(sid, doc.document_id)
    # 破坏派生投影（事实不动）：清空向量 + 构建行。
    await env.document_repository.replace_vectors(sid, doc.document_id, [])
    assert await env.document_repository.get_vectors(sid, doc.document_id) == {}

    results = await env.lifecycle.rebuild_derived_indexes(sid)

    assert results[str(doc.document_id)]["status"] == "rebuilt"
    assert results[str(doc.document_id)]["index_version"] == 2  # force 重建递增
    # 向量 = FakeBackend 对 chunk 文本的确定性输出（事实未被改动）。
    chunks = await env.document_repository.list_chunks(sid, doc.document_id)
    expected = await env.runtime.embed_texts([chunk.text for chunk in chunks])
    vectors = await env.document_repository.get_vectors(sid, doc.document_id)
    assert [vector for _, (_, vector) in sorted(vectors.items(), key=lambda p: str(p[0]))] == list(expected)
    assert len(chunks) == 1 and chunks[0].text == _SEED_BODY
    # 绝不重导入用户原文件：文档数不变、存储文件还在。
    assert len(await env.document_repository.list_documents(sid)) == 1
    assert await env.storage.exists(doc.storage_ref) is True


async def test_rebuild_derived_indexes_unavailable_without_backend(env) -> None:
    sid = _sid()
    doc = await _seed_document(env.document_repository, env.storage, sid)
    empty_doc = await _seed_document(
        env.document_repository,
        env.storage,
        sid,
        filename="empty.txt",
        body="空文档正文 EMPTY-BODY",
    )
    await env.document_repository.replace_chunks(sid, empty_doc.document_id, [])

    # 无 index manager。
    bare = DataLifecycleService(document_repository=env.document_repository)
    results = await bare.rebuild_derived_indexes(sid)
    assert results[str(doc.document_id)]["status"] == "unavailable"
    assert results[str(empty_doc.document_id)]["status"] == "unavailable"
    # 无 backend 的 runtime（manager 在、backend 缺）。
    manager = DocumentIndexManager(
        repository=env.document_repository, embedding_runtime=EmbeddingRuntime()
    )
    degraded = DataLifecycleService(
        document_repository=env.document_repository, index_manager=manager
    )
    results = await degraded.rebuild_derived_indexes(sid)
    assert results[str(doc.document_id)]["status"] == "unavailable"
    assert results[str(empty_doc.document_id)]["status"] == "unavailable"
    # 有 backend 时：无 chunk 事实的文档诚实地标注 no_chunks，不伪造。
    results = await env.lifecycle.rebuild_derived_indexes(sid)
    assert results[str(doc.document_id)]["status"] == "rebuilt"
    assert results[str(empty_doc.document_id)]["status"] == "no_chunks"


# ---------------------------------------------------------------------------
# 7/8. delete_educational_history — replay, not hardcoded values; idempotent.
# ---------------------------------------------------------------------------


async def test_delete_educational_history_replays_projection(env) -> None:
    sid, other = _sid(), _sid()
    seeded = await _seed_education(env.uow, sid, attempts=2)
    other_seeded = await _seed_education(env.uow, other, attempts=1)

    summary = await env.lifecycle.delete_educational_history(sid)

    assert summary["deleted_rows"] > 0
    sid_attempt_ids = [str(attempt_id) for attempt_id in seeded["attempt_ids"]]
    async with env.uow.transaction() as conn:
        # sid 的四个学生维度结果表清零（按 owner 统计，other 不受影响）。
        for table in (
            mastery_evidence,
            misconception_observations,
            attempts,
            attempt_submissions,
        ):
            count = int(
                (
                    await conn.execute(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.student_id == sid)
                    )
                ).scalar()
                or 0
            )
            assert count == 0, table.name
        # attempt_assessments 无 student_id 列 → 以 sid 的 attempt_ids 界定。
        assert int(
            (
                await conn.execute(
                    select(func.count())
                    .select_from(attempt_assessments)
                    .where(attempt_assessments.c.attempt_id.in_(sid_attempt_ids))
                )
            ).scalar()
            or 0
        ) == 0
        # attempt 链接的 verification_logs 已删；candidate 链接的内容权威存活
        #（sid 与 other 各自的 candidate 日志都在 — 内容权威从不随学生删除）。
        candidate_logs = (
            await conn.execute(
                select(verification_logs).where(verification_logs.c.attempt_id.is_(None))
            )
        ).all()
        assert {row.log_id for row in candidate_logs} == {
            seeded["reference_log_id"],
            other_seeded["reference_log_id"],
        }
        # 其他学生不受影响（own 的 attempt 行仍在）。
        assert int(
            (
                await conn.execute(
                    select(func.count())
                    .select_from(attempts)
                    .where(attempts.c.student_id == other)
                )
            ).scalar()
            or 0
        ) == 1
        # 会话骨架保留（两个学生各一个 cycle）。
        assert int(
            (
                await conn.execute(
                    select(func.count()).select_from(tutoring_cycles)
                )
            ).scalar()
            or 0
        ) == 2
        projection = await sqlite_education.load_student_projection(conn, sid)
    # 重放投影：剩余 evidence（空）的投影 — 与 project_student_state 输出逐字段一致。
    expected = project_student_state(
        student_id=student_uuid(sid), evidence=[], observations=[]
    )
    assert projection is not None
    assert projection["projection_version"] == expected.projection_version == 0
    assert projection["estimator_version"] == expected.estimator_version
    assert projection["skill_mastery"] == list(expected.skill_mastery)
    assert projection["concept_mastery"] == list(expected.concept_mastery)
    assert projection["active_misconceptions"] == list(expected.active_misconceptions)
    # 骨架中的权威记录仍在（problem submission 是入口记录，未被误删）。
    assert await _count(env, tutoring_cycles) == 2


async def test_delete_educational_history_idempotent(env) -> None:
    sid = _sid()
    await _seed_education(env.uow, sid, attempts=2)
    first = await env.lifecycle.delete_educational_history(sid)
    assert first["deleted_rows"] > 0
    async with env.uow.transaction() as conn:
        projection_before = await sqlite_education.load_student_projection(conn, sid)

    second = await env.lifecycle.delete_educational_history(sid)

    assert second["deleted_rows"] == 0  # 无副作用
    for table in (
        mastery_evidence,
        misconception_observations,
        attempt_assessments,
        attempts,
        attempt_submissions,
    ):
        assert await _count(env, table) == 0, table.name
    async with env.uow.transaction() as conn:
        projection_after = await sqlite_education.load_student_projection(conn, sid)
    # 重复调用结果一致（updated_at 会变，比较投影字段本身）。
    assert _projection_key(projection_after) == _projection_key(projection_before)


async def test_v2_history_deletion_clears_events_snapshots_and_teaching_progress(env, tmp_path):
    """An explicit privacy operation erases results; restart cannot hydrate stale progress."""
    from mathtutor.learning.knowledge_tracing.service import StudentStateService
    from mathtutor.learning.knowledge_tracing.schema import learning_events, learning_predictions, student_state_snapshots
    from mathtutor.repositories.teaching_repository import TeachingRepository

    sid, other = _sid(), _sid()
    owned = await _seed_education(env.uow, sid, attempts=1)
    foreign = await _seed_education(env.uow, other, attempts=1)
    state = StudentStateService(env.engine)
    teaching = TeachingRepository(env.engine)
    for owner, fixture in ((sid, owned), (other, foreign)):
        await state.record_attempt(owner, session_id="session", cycle_id=str(fixture["cycle_id"]),
            problem_id=str(fixture["problem_id"]), problem_revision="r1", item_family_id="linear",
            skill_ids=("LINEAR_EQUATION",), assessment_id=str(uuid4()), attempt_id=str(fixture["attempt_ids"][0]), correctness="correct")
        await teaching.save(owner, fixture["cycle_id"], {
            "schema_version": "mt-teaching-v2", "skill_graph_version": "test-graph",
            "problem_id": str(fixture["problem_id"]), "problem_revision": "r1", "display_text": "2x+3=7",
            "skill_ids": ["LINEAR_EQUATION"], "lifecycle": "completed", "current_subgoal_index": 1,
            "subgoals": [{"id": "isolate", "prompt_target": "求未知数", "skill_ids": ["LINEAR_EQUATION"], "status": "verified"}],
            "progress": [{"text": "ANSWER-TO-ERASE", "verified_claims": [{"variable": "x", "value": 2}]}],
            "assessments": [{"raw_text": "ANSWER-TO-ERASE", "task_completion": "complete"}],
            "diagnosis": {"status": "completed", "results": [{"correctness": "correct"}]},
            "last_plan": {"evidence_refs": ["old-assessment"]}, "error_analysis": {"student_response": "ANSWER-TO-ERASE"},
            "pending_expression": {"request_id": "request-to-erase", "student_request": "ANSWER-TO-ERASE",
                "feedback": "FEEDBACK-TO-ERASE", "approved_utterance": {"text": "OLD-APPROVED-REPLY"},
                "continuation_context": "OLD-CONTINUATION"},
            "language_understanding": {"evidence_quote": "ANSWER-TO-ERASE", "confusion": "persistent"},
            "language_input_hash": "OLD-INPUT-HASH", "language_request_id": "request-to-erase",
            "language_signal_consumed_request": "request-to-erase",
            "task_context": {"schema_version": "mt-problem-context-v1", "problem_id": str(fixture["problem_id"]),
                "cycle_id": str(fixture["cycle_id"]), "problem_revision": "r1", "source_ref": {"submission_id": "source-navigation"},
                "original_statement": "解方程 2x+3=7", "full_statement": "解方程 2x+3=7",
                "normalized_representation": {"kind": "equation"}, "task_kind": "solve_equation",
                "task_type": "linear", "domain": "unknown", "units": "cm", "precision": {"decimal_places": 2},
                "expected_answer_shape": {"kind": "root_set", "variables": ["x"]},
                "verified_solution_ref": {"verification_log_id": "retained-reference"}, "verification_status": "verified",
                "current_subgoal_id": "old-subgoal", "verified_student_steps": [{"text": "ANSWER-TO-ERASE"}],
                "help_exposure": [{"text": "OLD-HELP-TO-ERASE", "target_answer_exposed": True}],
                "unanswered_question": {"text": "OLD-QUESTION-TO-ERASE"},
                "used_examples": [{"problem": "OLD-EXAMPLE-TO-ERASE"}],
                "invitation_source": {"student_response": "ANSWER-TO-ERASE"},
                "future_recovery_cache": {"text": "OLD-APPROVED-REPLY"}},
        })
    weights = tmp_path / "local-model.safetensors"
    credentials = tmp_path / "secure-store-test.enc"
    weights.write_bytes(b"nonsecret-model-marker")
    credentials.write_bytes(b"encrypted-test-marker")

    summary = await env.lifecycle.delete_educational_history(sid)
    assert summary["teaching_contexts_cleared"] == 1
    for table in (learning_events, learning_predictions, student_state_snapshots):
        assert summary["by_table"][table.name] == 1
        async with env.uow.transaction() as conn:
            assert (await conn.execute(select(func.count()).select_from(table).where(table.c.student_id == sid))).scalar_one() == 0
            assert (await conn.execute(select(func.count()).select_from(table).where(table.c.student_id == other))).scalar_one() == 1
    restarted = StudentStateService(env.engine)
    assert await restarted.import_legacy(sid) == 0
    learner = await restarted.summary(sid)
    assert learner["event_count"] == 0 and learner["skills"] == []
    assert learner["training_data"]["events"] == 0
    assert (await restarted.summary(other))["event_count"] == 1
    clean = await TeachingRepository(env.engine).load(sid, owned["cycle_id"])
    assert clean["problem_id"] == str(owned["problem_id"])
    assert clean["display_text"] == "2x+3=7"
    assert clean["progress"] == [] and clean["assessments"] == []
    assert clean["subgoals"][0]["status"] == "pending"
    assert clean["diagnosis"]["status"] == "not_started"
    assert clean["legacy_provenance_uncertain"] is True
    assert "ANSWER-TO-ERASE" not in str(clean)
    for key in ("pending_expression", "language_understanding", "language_input_hash", "language_request_id",
                "language_signal_consumed_request"):
        assert key not in clean
    for marker in ("FEEDBACK-TO-ERASE", "OLD-APPROVED-REPLY", "OLD-CONTINUATION", "OLD-HELP-TO-ERASE",
                   "OLD-QUESTION-TO-ERASE", "OLD-EXAMPLE-TO-ERASE", "OLD-INPUT-HASH", "request-to-erase"):
        assert marker not in str(clean)
    task = clean["task_context"]
    assert task["problem_id"] == str(owned["problem_id"]) and task["cycle_id"] == str(owned["cycle_id"])
    assert task["original_statement"] == task["full_statement"] == "解方程 2x+3=7"
    assert task["source_ref"] == {"submission_id": "source-navigation"}
    assert task["normalized_representation"] == {"kind": "equation"}
    assert task["units"] == "cm" and task["precision"] == {"decimal_places": 2}
    assert task["verified_solution_ref"]["verification_log_id"] == "retained-reference"
    assert task["verified_student_steps"] == task["used_examples"] == []
    assert task["unanswered_question"] is task["invitation_source"] is None
    assert task["help_exposure"]["provenance_uncertain"] is True
    assert task["student_progress_status"] == task["example_history_status"] == "unknown"
    assert task["current_subgoal_id"] == "isolate"
    assert (await teaching.load(other, foreign["cycle_id"]))["lifecycle"] == "completed"
    assert (await teaching.load(other, foreign["cycle_id"]))["pending_expression"]["approved_utterance"]["text"] == "OLD-APPROVED-REPLY"
    second = await env.lifecycle.delete_educational_history(sid)
    assert second["deleted_rows"] == 0 and second["teaching_contexts_cleared"] == 0
    assert weights.read_bytes() == b"nonsecret-model-marker"
    assert credentials.read_bytes() == b"encrypted-test-marker"


def test_data_lifecycle_source_never_writes_mastery_values() -> None:
    """Static guard: the lifecycle module only REPLAYS projections — it has
    no path that assigns mastery values, no CAS update, no estimator use,
    and no evidence factory (facts are only ever deleted here)."""
    import mathtutor.application.data_lifecycle as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "project_student_state(" in source
    assert "upsert_student_state(" in source
    assert "student_state_projections.update" not in source
    assert "skill_mastery = " not in source
    assert "concept_mastery = " not in source
    assert not re.search(r"mastery\s*=\s*0\b", source)
    assert not re.search(r'"mastery"\s*:\s*0', source)
    assert "MasteryEstimator" not in source
    assert "initial_mastery" not in source
    assert "insert_mastery_evidence" not in source


# ---------------------------------------------------------------------------
# 9. Educational-history deletion ≠ Memory CRUD (both directions).
# ---------------------------------------------------------------------------


async def test_educational_history_delete_is_not_memory_crud(env) -> None:
    sid = _sid()
    await _seed_education(env.uow, sid, attempts=1)
    keep = await env.memory.add_explicit(
        sid,
        memory_type="learning_preference",
        subject="节奏",
        predicate="prefers",
        object_json={"pace": "慢"},
    )
    drop = await env.memory.add_explicit(
        sid,
        memory_type="user_note",
        subject="临时",
        predicate="says",
        object_json={"text": "删"},
    )

    # 方向一：删教育历史 → 记忆行不受影响。
    await env.lifecycle.delete_educational_history(sid)
    live = await env.memory_repository.list_nodes(sid)
    assert {node.memory_id for node in live} == {keep.memory_id, drop.memory_id}
    # 方向二：删记忆 → 教育表不受影响（此处已删空，验证不新增/不复活）。
    await env.lifecycle.delete_personal_memory(sid, drop.memory_id)
    for table in (
        mastery_evidence,
        misconception_observations,
        attempt_assessments,
        attempts,
        attempt_submissions,
    ):
        assert await _count(env, table) == 0, table.name
    remaining = await env.memory_repository.list_nodes(sid)
    assert [node.memory_id for node in remaining] == [keep.memory_id]


# ---------------------------------------------------------------------------
# 10. Export — whitelist fields only; sensitive fields structurally absent.
# ---------------------------------------------------------------------------


async def test_export_whitelist_only_no_sensitive_fields(env) -> None:
    sid = _sid()
    doc = await _seed_document(env.document_repository, env.storage, sid)
    await env.memory.add_explicit(
        sid,
        memory_type="learning_goal",
        subject="目标",
        predicate="wants",
        object_json={"goal": "EXPORT-GOAL-MARKER"},
    )
    seeded = await _seed_education(env.uow, sid, attempts=2)

    export = await build_student_export(
        student_id=sid,
        documents=env.documents,
        memory=env.memory,
        uow=env.uow,
    )

    assert set(export) == {"meta", "documents", "memory", "student_summary"}
    validate_export(export)  # 白名单校验通过
    assert export["meta"]["student_id"] == sid
    assert export["meta"]["schema_version"] == "mt-export-v2"
    # documents：公共投影字段，且不泄露存储路径/哈希。
    assert len(export["documents"]) == 1
    doc_entry = export["documents"][0]
    assert set(doc_entry) <= EXPORT_ALLOWED_FIELDS["documents"]
    assert doc_entry["document_id"] == str(doc.document_id)
    assert doc_entry["filename"] == "notes.txt"
    # memory：公共投影字段。
    assert len(export["memory"]) == 1
    assert set(export["memory"][0]) <= EXPORT_ALLOWED_FIELDS["memory"]
    assert export["memory"][0]["object_json"] == {"goal": "EXPORT-GOAL-MARKER"}
    # student summary：persisted 投影的可读字段。
    summary = export["student_summary"]
    assert set(summary) <= EXPORT_ALLOWED_FIELDS["student_summary"]
    assert summary["total_attempts"] == 2
    assert summary["projection_version"] == 0  # No v2 events exist in this legacy fixture.
    assert summary["estimator_version"] == "evidence_tracker_v2"
    assert sum(row["evidence_summary"]["ungradable"] for row in summary["skills"]) == 2
    assert all("mastery" not in row for row in summary["skills"])
    from mathtutor.learning.knowledge_tracing.schema import learning_events
    assert await _count(env, learning_events) == 0  # Export never performs a hidden migration.
    # 敏感字段逐字段缺席（构造的敏感数据一个都不能出现）。
    dumped = json.dumps(export, ensure_ascii=False, default=str)
    for marker in (
        "CAND-ATTEST-MARKER",
        "ATT-MARK-",
        "RAW-ANSWER-MARKER",
        "seed-attempt-",
        "seed-evidence-",
        "seed-candidate-",
        doc.storage_ref,  # 存储路径
        doc.content_hash,  # 哈希
        _SEED_BODY,  # chunk 原文
    ):
        assert marker not in dumped, marker
    for forbidden_fragment in ("attestation", "reasoning", "payload", "hash", "storage"):
        for key in _walk_keys(export):
            assert forbidden_fragment not in key.lower(), (forbidden_fragment, key)


def test_export_validation_rejects_unknown_fields() -> None:
    valid = {
        "meta": {"schema_version": "v", "exported_at": "t", "student_id": "s"},
        "documents": [],
        "memory": [],
        "student_summary": {
            "total_attempts": 0,
            "estimator_version": "",
            "projection_version": None,
            "skills": [],
            "active_misconceptions": [],
        },
    }
    validate_export(valid)
    with pytest.raises(ExportValidationError):
        validate_export({**valid, "extra_section": []})
    with pytest.raises(ExportValidationError):
        validate_export({**valid, "student_summary.skills": {"api_key": "must-not-export"}})
    with pytest.raises(ExportValidationError):
        bad = json.loads(json.dumps(valid))
        bad["documents"].append({"document_id": "x", "storage_ref": "uploads/x"})
        validate_export(bad)
    with pytest.raises(ExportValidationError):
        bad = json.loads(json.dumps(valid))
        bad["student_summary"]["skills"].append({"skill_id": "S", "evidence_status": "仍需确认",
            "evidence_summary": {"independent": {"correct": 1, "incorrect": 0, "api_key": "must-not-export"}}})
        validate_export(bad)
    with pytest.raises(ExportValidationError):
        bad = json.loads(json.dumps(valid))
        bad["student_summary"]["skills"].append(
            {"skill_id": "S", "mastery": 0.5, "attestation": "no"}
        )
        validate_export(bad)


async def test_legacy_verified_binding_preserved_without_inventing_help_chronology(env):
    from mathtutor.learning.knowledge_tracing.service import StudentStateService
    sid = _sid()
    seeded = await _seed_education(env.uow, sid, attempts=1)
    tracker = StudentStateService(env.engine)
    assert await tracker.import_legacy(sid) == 1
    facts = await tracker.events(sid)
    assert facts[0].problem_id == str(seeded["problem_id"])
    canonical = f"seed-problem-{seeded['problem_id']}"
    assert facts[0].problem_revision == canonical
    assert facts[0].provenance_uncertain and not facts[0].independent_target
    context = await tracker.exposure_context(sid, canonical)
    assert context["provenance_uncertain"] and not context["target_answer_exposed"]
    # The legacy record proves neither "never helped" nor "read the answer".
    new_attempt = await tracker.record_attempt(sid, session_id="another-conversation", cycle_id="another-cycle",
        problem_id=str(seeded["problem_id"]), problem_revision=canonical, item_family_id="linear",
        skill_ids=["linear_isolation"], assessment_id="new-assessment", attempt_id="new-attempt", correctness="correct")
    assert new_attempt.provenance_uncertain and new_attempt.evidence_kind == "unknown"
    assert not (await tracker.exposure_context(sid, "genuinely-new-task"))["provenance_uncertain"]


# ---------------------------------------------------------------------------
# 11. Log safety — sanitize_summary + real service logs carry no plaintext.
# ---------------------------------------------------------------------------


def test_sanitize_summary_redacts_sensitive_keys() -> None:
    clean = sanitize_summary(
        {
            "api_key": "sk-marker-123",
            "raw_text": "RAW-TEXT-MARKER",
            "object_json": {"note": "私密"},
            "attestation": "ATT-MARK",
            "count": 3,
            "doc_id": str(uuid4()),
        }
    )
    dumped = json.dumps(clean, ensure_ascii=False, default=str)
    assert "sk-marker-123" not in dumped
    assert "RAW-TEXT-MARKER" not in dumped
    assert "ATT-MARK" not in dumped
    assert clean["count"] == 3
    assert clean["api_key"] == "<redacted>"
    assert clean["raw_text"] == "<redacted>"
    assert clean["object_json"] == "<redacted>"
    assert clean["attestation"] == "<redacted>"


async def test_lifecycle_and_export_logs_are_sanitized(env, caplog) -> None:
    sid = _sid()
    await _seed_education(env.uow, sid, attempts=1)
    doc = await _seed_document(
        env.document_repository,
        env.storage,
        sid,
        filename="secret-notes.txt",
        body="RAW-BODY-MARKER-42",
    )
    caplog.set_level(logging.INFO)
    await env.lifecycle.delete_educational_history(sid)
    await env.lifecycle.delete_document(sid, doc.document_id)
    await env.lifecycle.purge_user_documents(sid)
    await build_student_export(
        student_id=sid, documents=env.documents, memory=env.memory, uow=env.uow
    )
    text = caplog.text
    assert "RAW-BODY-MARKER-42" not in text
    assert "RAW-ANSWER-MARKER" not in text
    assert "ATT-MARK-" not in text
    assert "CAND-ATTEST-MARKER" not in text
    assert "sk-" not in text


# ---------------------------------------------------------------------------
# 12. No trash + schema inventory remains explicit.
# ---------------------------------------------------------------------------


def test_schema_table_count_unchanged_and_migrations_are_explicit() -> None:
    from mathtutor.infrastructure import schema as schema_module

    assert set(schema_module.metadata.tables) == set(DATA_CATEGORIES)
    assert len(schema_module.metadata.tables) == 57  # 024: turn traces
    versions_dir = (
        Path(schema_module.__file__).resolve().parent / "migrations" / "versions"
    )
    versions = sorted(path.name for path in versions_dir.glob("*.py"))
    assert versions == [
        "001_initial_schema.py",
        "002_misconceptions.py",
        "003_personal_memory_and_documents.py",
        "004_practice_release.py",
        "005_curriculum_and_outbox_relay.py",
        "006_evidence_identity.py",
        "007_document_parse_stats.py",
        "008_document_chunk_fts.py",
        "009_conversation_workspace.py",
        "010_turn_completion.py",
        "011_turn_requests.py",
        "012_teaching_contexts.py",
        "013_practice_recommendations.py",
        "014_learning_tracking.py",
        "015_image_attachments.py",
        "016_document_scope.py",
        "017_conversation_trash.py",
        "018_learning_profile.py",
        "019_initial_assessment.py",
        "020_knowledge_workbench.py",
        "021_document_parser_provenance.py",
        "022_index_signature_normalization.py",
        "023_citation_receipts.py",
        "024_turn_traces.py",
    ]


def _walk_keys(node, prefix: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            full = f"{prefix}.{key}" if prefix else key
            yield full
            yield from _walk_keys(value, full)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_keys(value, f"{prefix}[{index}]")

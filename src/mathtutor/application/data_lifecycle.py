"""Data lifecycle service — privacy deletion, purge, rebuild, classification.

Phase 6 round 2 (SUBAGENT D): the ONE application surface for per-student
data lifecycle operations, wired later by MAIN into the desktop privacy
panel. This module is constructed by injection only — it never imports
``product_state`` and it modifies no existing file.

Five-category classification (design doc §14 / §6.1 / risk P2):

- ``AUTHORITY_EDUCATIONAL`` — 学生维度的权威教育事实（attempt / assessment /
  evidence / observation / 教学行为记录）。只允许通过
  :meth:`DataLifecycleService.delete_educational_history` 删除，绝不与
  Personal Memory CRUD 混用同一入口或语义。
- ``USER_CONTROLLED`` — 学生自有的可管理数据（导入的文档 / chunks / 个人记忆）。
  通过 ``delete_document`` / ``delete_personal_memory`` / purge 删除。
- ``DERIVED`` — 派生投影（StudentState、chunk vectors、index build 行）。
  只能从事实重放/重建（不变量 B/E），永不作为删除的源头。
- ``SYSTEM`` — 共享内容目录与运行骨架（身份、会话、cycle、状态机审计、
  outbox 台账、curriculum、练习目录、数学事实目录）。不随学生生命周期删除。
- ``SECRET`` — credential 与 attestation/reasoning/trace/payload/原文/路径/
  哈希/向量类字段。永不导出、永不进日志；数据库中今天没有凭据表（API key
  只在 OS SecretStore），SECRET 以字段级分类存在。

Deletion semantics (status quo, read from code — NOT changed here):

- documents: row SOFT delete (``deleted_at`` set, row kept) + controlled
  storage file removed immediately; NO trash/recycle bin (domain:
  ``DOCUMENT_RETENTION_DELETE_IMMEDIATELY``). This service additionally
  hard-deletes the chunk facts and the derived vector/index rows so the
  student's content is really gone (chunks are user content, not system
  facts — they die with their document).
- personal memory: row SOFT delete only (repo protocol has no edge-delete
  path; nodes are the retrieval surface).
- educational history: authoritative rows are HARD deleted inside one short
  transaction, then the StudentState projection is REPLAYED from the
  remaining evidence via ``project_student_state`` and re-persisted via
  ``upsert_student_state`` (invariant B: the projection is derived — this
  module never writes mastery values itself; the baseline after a full wipe
  is the replay's natural result, not a hardcoded value).

Log safety: every operation logs only a whitelist-shaped, sanitized summary
(:func:`sanitize_summary`) — never payloads, attestations, raw text, paths
or keys.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from mathtutor.application.document_ingestion import (
    DocumentIndexManager,
    DocumentIngestionService,
)
from mathtutor.application.personal_memory_service import (
    PersonalMemoryService,
)
from mathtutor.domain.embedding import EmbeddingUnavailableError
from mathtutor.infrastructure.observability import sanitize_for_logs
from mathtutor.infrastructure.schema import (
    attempt_assessments,
    attempt_submissions,
    attempts,
    document_index_builds,
    mastery_evidence,
    misconception_observations,
    student_state_projections,
    verification_logs,
    teaching_contexts,
)
from mathtutor.learning.knowledge_tracing.schema import learning_events, learning_predictions, student_state_snapshots, learning_generations, practice_feedback, initial_assessments
from mathtutor.learning.projection import project_student_state
from mathtutor.repositories import sqlite_education
from mathtutor.repositories.document_repository import (
    DocumentRepository,
)
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.security.scopes import student_uuid

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Five-category data classification (single source of truth for lifecycle).
# ---------------------------------------------------------------------------

CATEGORY_AUTHORITY_EDUCATIONAL = "AUTHORITY_EDUCATIONAL"
CATEGORY_USER_CONTROLLED = "USER_CONTROLLED"
CATEGORY_DERIVED = "DERIVED"
CATEGORY_SYSTEM = "SYSTEM"
CATEGORY_SECRET = "SECRET"

DATA_CATEGORY_VALUES: frozenset[str] = frozenset(
    {
        CATEGORY_AUTHORITY_EDUCATIONAL,
        CATEGORY_USER_CONTROLLED,
        CATEGORY_DERIVED,
        CATEGORY_SYSTEM,
        CATEGORY_SECRET,
    }
)

#: table → category, covering EVERY business table in infrastructure/schema.py.
DATA_CATEGORIES: dict[str, str] = {
    # runtime / identity — account and session skeleton, never per-student
    # lifecycle data.
    "users": CATEGORY_SYSTEM,
    "student_profiles": CATEGORY_SYSTEM,
    "learning_sessions": CATEGORY_SYSTEM,
    "tutoring_cycles": CATEGORY_SYSTEM,
    "cycle_transitions": CATEGORY_SYSTEM,
    "cycle_focus": CATEGORY_SYSTEM,
    # math facts chain — shared content authority (never student-owned).
    "math_problems": CATEGORY_SYSTEM,
    "solution_candidates": CATEGORY_SYSTEM,
    # education — student-scoped authoritative facts.
    "problem_submissions": CATEGORY_AUTHORITY_EDUCATIONAL,
    "verification_logs": CATEGORY_AUTHORITY_EDUCATIONAL,
    "attempt_submissions": CATEGORY_AUTHORITY_EDUCATIONAL,
    "attempts": CATEGORY_AUTHORITY_EDUCATIONAL,
    "attempt_assessments": CATEGORY_AUTHORITY_EDUCATIONAL,
    "tutor_actions": CATEGORY_AUTHORITY_EDUCATIONAL,
    "assistance_issuances": CATEGORY_AUTHORITY_EDUCATIONAL,
    "mastery_evidence": CATEGORY_AUTHORITY_EDUCATIONAL,
    "misconception_observations": CATEGORY_AUTHORITY_EDUCATIONAL,
    "practice_offers": CATEGORY_AUTHORITY_EDUCATIONAL,
    "practice_recommendations": CATEGORY_AUTHORITY_EDUCATIONAL,
    "teaching_deliveries": CATEGORY_AUTHORITY_EDUCATIONAL,
    "learning_events": CATEGORY_AUTHORITY_EDUCATIONAL,
    "initial_assessments": CATEGORY_AUTHORITY_EDUCATIONAL,
    "learning_generations": CATEGORY_SYSTEM,
    "practice_feedback": CATEGORY_USER_CONTROLLED,
    # derived projections — rebuildable from facts, never a deletion source.
    "student_state_projections": CATEGORY_DERIVED,
    "document_chunk_vectors": CATEGORY_DERIVED,
    "document_index_builds": CATEGORY_DERIVED,
    "learning_predictions": CATEGORY_DERIVED,
    "student_state_snapshots": CATEGORY_DERIVED,
    "teaching_contexts": CATEGORY_DERIVED,
    # user-controlled content — the student's own documents and memories.
    "user_documents": CATEGORY_USER_CONTROLLED,
    "document_chunks": CATEGORY_USER_CONTROLLED,
    "conversations": CATEGORY_USER_CONTROLLED,
    "conversation_messages": CATEGORY_USER_CONTROLLED,
    "image_attachments": CATEGORY_USER_CONTROLLED,
    "turn_requests": CATEGORY_USER_CONTROLLED,
    "conversation_documents": CATEGORY_USER_CONTROLLED,
    "personal_memory_nodes": CATEGORY_USER_CONTROLLED,
    "personal_memory_edges": CATEGORY_USER_CONTROLLED,
    # system ledgers and shared catalogs.
    "domain_outbox": CATEGORY_SYSTEM,
    "outbox_dispatch_ledger": CATEGORY_SYSTEM,
    "curriculum_versions": CATEGORY_SYSTEM,
    "curriculum_nodes": CATEGORY_SYSTEM,
    "curriculum_edges": CATEGORY_SYSTEM,
    "exercises": CATEGORY_SYSTEM,
    "exercise_releases": CATEGORY_SYSTEM,
}

#: 分类理由（表 → 一句话依据），来源：infrastructure/schema.py + 设计文档。
DATA_CATEGORY_REASONS: dict[str, str] = {
    "users": "账户/角色身份（Phase 0 身份），非学生数据，永不随学生生命周期删除",
    "student_profiles": "user→student 身份映射，SYSTEM 骨架",
    "learning_sessions": "会话骨架（客户端会话 id 唯一约束），非教育结果",
    "tutoring_cycles": "教学会话骨架（状态机 CAS 载体）——明确不在教育历史删除集",
    "cycle_transitions": "append-only 状态机审计，会话骨架的一部分",
    "cycle_focus": "会话当前题目指针，保留用于路由恢复",
    "problem_submissions": "学生提交的题目原文（含 raw_text），权威教育事实；作为 cycle 的入口记录保留在删除集之外",
    "math_problems": "canonical 数学事实目录（共享内容权威，非学生数据）",
    "solution_candidates": "标准解候选目录（共享内容权威）",
    "verification_logs": "验证权威记录（XOR subject）；attempt 链接者随教育历史删除，candidate 链接者属内容权威永久保留",
    "attempt_submissions": "学生作答原文（raw_text），权威教育事实，删除集",
    "attempts": "解析后的作答事实（parsed_steps），删除集",
    "attempt_assessments": "作答判定（attestation_hash），删除集",
    "tutor_actions": "权威教学行为记录（append-only），随会话骨架保留",
    "assistance_issuances": "assistance 台账（evidence factory 输入），随骨架保留",
    "mastery_evidence": "append-only 掌握证据（不变量 B 的事实），删除集",
    "misconception_observations": "append-only 迷思观察，删除集",
    "practice_offers": "学生维度的练习发放记录（练习骨架），保留",
    "practice_recommendations": "练习推荐目的与发放状态审计，和邀请骨架一起保留",
    "teaching_deliveries": "帮助内容交付与暴露收据，保留以免删除历史后恢复独立资格",
    "learning_events": "v2权威学习事件，随授权教育历史删除，不从旧聊天重建",
    "initial_assessments": "初评选择题事实和规则起点，随教育历史删除，不进入来源DKT状态",
    "learning_generations": "只保存删除代次，不保存题目、作答或学习状态；阻止旧任务回写",
    "practice_feedback": "推荐反馈，随学习历史删除，不作为能力证据",
    "learning_predictions": "可重算的历史预测记录，随教育历史删除",
    "student_state_snapshots": "从学习事件重放得到的追踪器状态，随事实删除以防旧状态恢复",
    "teaching_contexts": "题目骨架上的教学进度投影；清除作答/诊断结果，保留题目绑定",
    "student_state_projections": "StudentState 投影（由 evidence 重放派生，不变量 B）",
    "document_chunk_vectors": "embedding 向量投影（由 chunks 派生，不变量 E）",
    "document_index_builds": "索引构建生命周期行（派生的构建签名）",
    "user_documents": "学生导入的文档元数据（用户自有权，软删语义）",
    "document_chunks": "chunk 文本事实（用户内容；随文档删除真实清理）",
    "conversations": "学生创建的对话标题与时间信息（用户可控工作区数据）",
    "conversation_messages": "学生与 Tutor 的可恢复对话记录（用户可控内容）",
    "image_attachments": "本地图片附件，可通过图片接口按用户删除；备份包含图片",
    "turn_requests": "按用户和对话隔离的请求结果台账（含已批准回复）",
    "conversation_documents": "对话与资料的用户显式关联（用户可控边界）",
    "personal_memory_nodes": "个人记忆 KG 节点（USER_CONTROLLED，软删）",
    "personal_memory_edges": "个人记忆 KG 边（节点附属结构）",
    "domain_outbox": "事件审计/传输台账（append-only）",
    "outbox_dispatch_ledger": "relay 幂等台账（append-only）",
    "curriculum_versions": "共享课程目录（非学生数据）",
    "curriculum_nodes": "共享课程节点目录",
    "curriculum_edges": "共享课程边目录",
    "exercises": "共享练习内容目录",
    "exercise_releases": "练习发布快照（内容权威）",
}

#: credential 命名片段 → SECRET（凭据相关；今天 DB 内无凭据列，SecretStore 在库外）。
SECRET_FIELD_FRAGMENTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
)

#: attestation / reasoning / trace / payload / 原文 / 存储路径 / 哈希 / 向量 /
#: 内部校验明细 —— 与 SECRET 同等待遇：永不导出、永不进日志。
SENSITIVE_FIELD_FRAGMENTS: tuple[str, ...] = (
    "attestation",
    "reasoning",
    "trace",
    "payload",
    "raw_text",
    "storage_ref",
    "hash",
    "vector",
    "checks",
    "steps",
    "detail",
    "chosen_action",
    "text",  # chunk 原文（document_chunks.text）等用户内容字段
)


def classify_table(table_name: str) -> str:
    """The lifecycle category of one business table (fail closed)."""
    try:
        return DATA_CATEGORIES[table_name]
    except KeyError:
        raise ValueError(
            f"数据表 {table_name!r} 未纳入五类数据分类 —— "
            "全部业务表必须显式分类（SECRET 仅以字段级存在）"
        ) from None


def classify_field(table_name: str, field: str) -> str | None:
    """Field-level classification: SECRET for credential/attestation/payload/
    raw-text/path/hash/vector-class fields (never exported, never logged),
    None for ordinary fields. Unknown table raises (fail closed)."""
    classify_table(table_name)  # unknown tables raise before field checks
    normalized = field.lower().replace("-", "_").replace(" ", "_")
    if any(fragment in normalized for fragment in SECRET_FIELD_FRAGMENTS):
        return CATEGORY_SECRET
    if any(fragment in normalized for fragment in SENSITIVE_FIELD_FRAGMENTS):
        return CATEGORY_SECRET
    return None


# ---------------------------------------------------------------------------
# Educational-history scope (invariant B: facts deleted, projection replayed).
# ---------------------------------------------------------------------------

#: 教育结果事实表 —— delete_educational_history 整学生硬删（行无软删字段）。
EDUCATIONAL_RESULT_TABLES: tuple[str, ...] = (
    "initial_assessments",
    "learning_events",
    "learning_predictions",
    "student_state_snapshots",
    "mastery_evidence",
    "misconception_observations",
    "attempt_assessments",
    "attempts",
    "attempt_submissions",
)

#: 部分删除表：只删 attempt 链接的行（candidate 链接 = 内容权威，永随内容保留）。
EDUCATIONAL_RESULT_PARTIAL_TABLES: frozenset[str] = frozenset({"verification_logs"})

#: 会话骨架与权威记录 —— 明确保留（宁可不删骨架，也不删错权威记录）。
EDUCATIONAL_SKELETON_KEPT: tuple[str, ...] = (
    "learning_sessions",
    "tutoring_cycles",
    "cycle_transitions",
    "problem_submissions",
    "tutor_actions",
    "assistance_issuances",
    "practice_offers",
    "domain_outbox",
    "outbox_dispatch_ledger",
    "cycle_focus",
    "practice_recommendations",
    "teaching_deliveries",
)


def _clear_teaching_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Retain the problem/navigation skeleton, never restore erased student claims."""
    from copy import deepcopy
    # This is deliberately a whitelist, not a growing blacklist of language
    # caches. pending_expression (including approved bytes and continuation),
    # language_understanding/evidence_quote, input hashes/request IDs and all
    # future transient teaching fields are excluded by default.
    retained = {key: deepcopy(payload[key]) for key in (
        "schema_version", "skill_graph_version", "problem_id", "problem_revision",
        "display_text", "skill_ids", "resume_parent_cycle_id", "client_session_id",
    ) if key in payload}
    goals = []
    for goal in payload.get("subgoals", []):
        goals.append({key: deepcopy(goal[key]) for key in ("id", "prompt_target", "skill_ids") if key in goal} | {"status": "pending"})
    task = payload.get("task_context")
    if isinstance(task, dict):
        # Preserve static canonical task conditions and navigation. In
        # particular, do not let the next hydration rebuild an incomplete
        # task from display_text alone. Results and recovery checkpoints are
        # not part of this retained, answer-free task projection.
        static_task = {key: deepcopy(task[key]) for key in (
            "schema_version", "problem_id", "cycle_id", "problem_revision", "canonicalization_version",
            "source", "source_ref", "original_statement", "full_statement", "statement_provenance",
            "display_text", "normalized_representation", "task_type", "task_kind", "task_objective",
            "solve_for", "domain", "units", "precision", "expected_answer_shape", "skill_ids",
            "skill_details", "skill_graph_version", "skill_label_version", "step_skill_map",
            "verified_solution_ref", "verification_status", "verification_reason", "verification_capability",
        ) if key in task}
        static_task.update({
            "current_subgoal_id": goals[0].get("id") if goals else None,
            "verified_student_steps": [], "student_progress_status": "unknown",
            "unanswered_question": None,
            "help_exposure": {"status": "unknown", "provenance_uncertain": True,
                              "reason": "educational_history_deleted"},
            "used_examples": [], "example_history_status": "unknown",
            "invitation_source": None,
        })
        retained["task_context"] = static_task
    retained.update({
        "lifecycle": "active", "current_subgoal_index": 0, "subgoals": goals,
        "progress": [], "assessments": [], "stuck_count": 0, "help_without_progress": 0,
        "help_fingerprints": [], "last_plan": None, "deliveries": [],
        # Deleted chronology cannot establish new independent mastery in the old cycle.
        "legacy_provenance_uncertain": True,
        "diagnosis": {"status": "not_started", "can_skip": True, "question_count": 0},
    })
    return retained


class LifecycleUnavailableError(ValueError):
    """The operation needs a dependency the caller did not inject."""


def sanitize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Log-safe copy of an operation summary (whitelist-shaped summaries only).

    Structural redaction on top of ``observability.sanitize_for_logs``: the
    observability forbid-list covers api_key/reasoning/attestation/payload/
    document; this module additionally redacts raw_text / object_json /
    subject / predicate / text / path / hash / vector / steps / detail keys
    so lifecycle logs can never carry student content.
    """
    extra_fragments = (
        "raw_text",
        "object_json",
        "subject",
        "predicate",
        "filename",
        "text",
        "path",
        "hash",
        "vector",
        "steps",
        "detail",
        "chosen_action",
        "checks",
    )
    cleaned: dict[str, Any] = {}
    for key, value in summary.items():
        safe = sanitize_for_logs(key, value)
        normalized = key.lower().replace("-", "_").replace(" ", "_")
        if any(fragment in normalized for fragment in extra_fragments):
            safe = "<redacted>"
        cleaned[key] = safe
    return cleaned


def _log_summary(action: str, summary: dict[str, Any]) -> None:
    payload = sanitize_summary({"action": action, **summary})
    logger.info("data lifecycle: %s", payload)


class DataLifecycleService:
    """Privacy/lifecycle operations, dependency-injected (never product_state).

    Every collaborator is optional at construction and demanded per
    operation; a missing dependency raises :class:`LifecycleUnavailableError`
    (fail closed — no silent partial deletion).
    """

    def __init__(
        self,
        *,
        documents: DocumentIngestionService | None = None,
        document_repository: DocumentRepository | None = None,
        storage: Any | None = None,  # DocumentStorage (avoid hard import cycle)
        memory: PersonalMemoryService | None = None,
        index_manager: DocumentIndexManager | None = None,
        uow: MathTutorUow | None = None,
    ) -> None:
        self._documents = documents
        self._document_repository = document_repository
        self._storage = storage
        self._memory = memory
        self._index = index_manager
        self._uow = uow

    # ------------------------------------------------------------- requires

    def _require_documents(self) -> DocumentIngestionService:
        if self._documents is None:
            raise LifecycleUnavailableError("文档生命周期操作需要 DocumentIngestionService")
        return self._documents

    def _require_document_repository(self) -> DocumentRepository:
        if self._document_repository is None:
            raise LifecycleUnavailableError("文档清理需要 DocumentRepository")
        return self._document_repository

    def _require_storage(self) -> Any:
        if self._storage is None:
            raise LifecycleUnavailableError("存储文件清理需要 DocumentStorage")
        return self._storage

    def _require_memory(self) -> PersonalMemoryService:
        if self._memory is None:
            raise LifecycleUnavailableError("记忆生命周期操作需要 PersonalMemoryService")
        return self._memory

    def _require_uow(self) -> MathTutorUow:
        if self._uow is None:
            raise LifecycleUnavailableError("教育历史删除/索引行清理需要 MathTutorUow")
        return self._uow

    # ------------------------------------------------------------- documents

    async def delete_document(self, student_id: str, document_id: Any) -> bool:
        """Delete ONE document, keeping the domain's deletion semantics.

        Row semantics unchanged (status quo): soft delete (``deleted_at``
        set, row retained, immediately invisible — no trash) + controlled
        storage file removed. The lifecycle service additionally makes the
        content cleanup REAL: chunk facts and derived vector/index-build
        rows are deleted in the same breath, so the student's content does
        not linger behind the tombstone row. Other students' data is
        structurally unreachable (owner-scoped statements).
        """
        service = self._require_documents()
        doc = await service.get_document(student_id, document_id)
        if doc is None:
            _log_summary("delete_document", {"doc_id": str(document_id), "deleted": False})
            return False
        deleted = await service.delete(student_id, document_id)  # soft delete + file removal
        if not deleted:
            _log_summary("delete_document", {"doc_id": str(document_id), "deleted": False})
            return False
        repository = self._require_document_repository()
        await repository.replace_chunks(student_id, document_id, [])  # chunk facts removed
        await repository.replace_vectors(student_id, document_id, [])  # derived vectors removed
        await self._delete_index_build(student_id, document_id)
        _log_summary("delete_document", {"doc_id": str(document_id), "deleted": True})
        return True

    async def purge_user_documents(self, student_id: str) -> dict[str, int]:
        """Wipe ALL of one student's document data (live AND already
        soft-deleted rows): soft-delete tombstones, hard-delete chunks +
        derived vectors/index rows, remove every controlled storage file.
        Never touches another student's rows or files."""
        repository = self._require_document_repository()
        storage = self._require_storage()
        docs = await repository.list_documents(student_id, include_deleted=True)
        summary = {
            "documents_soft_deleted": 0,
            "chunks_removed": 0,
            "vectors_cleared": 0,
            "index_builds_removed": 0,
            "storage_files_removed": 0,
        }
        for doc in docs:
            if doc.deleted_at is None:
                if await repository.soft_delete_document(student_id, doc.document_id):
                    summary["documents_soft_deleted"] += 1
            chunks = await repository.list_chunks(student_id, doc.document_id)
            await repository.replace_chunks(student_id, doc.document_id, [])
            summary["chunks_removed"] += len(chunks)
            await repository.replace_vectors(student_id, doc.document_id, [])
            summary["vectors_cleared"] += 1
            await self._delete_index_build(student_id, doc.document_id)
            summary["index_builds_removed"] += 1
            if await storage.remove(doc.storage_ref):
                summary["storage_files_removed"] += 1
        _log_summary("purge_user_documents", summary)
        return summary

    async def _delete_index_build(self, student_id: str, document_id: Any) -> None:
        """Remove the derived index-build row (no repo interface → short SQL)."""
        if self._uow is None:
            return
        async with self._uow.transaction() as conn:
            await conn.execute(
                sa_delete(document_index_builds).where(
                    document_index_builds.c.student_id == student_id,
                    document_index_builds.c.document_id == str(document_id),
                )
            )

    # --------------------------------------------------------------- memory

    async def delete_personal_memory(self, student_id: str, memory_id: Any) -> bool:
        """Personal-memory deletion — the PersonalMemoryService semantics,
        verbatim (soft delete, immediately invisible, no trash). This is
        USER_CONTROLLED data and has NO relationship to educational history:
        deleting a memory never touches the Student Model, by construction."""
        service = self._require_memory()
        deleted = await service.delete(student_id, memory_id)
        _log_summary(
            "delete_personal_memory", {"memory_id": str(memory_id), "deleted": deleted}
        )
        return deleted

    async def purge_personal_memory(self, student_id: str) -> dict[str, int]:
        """Soft-delete ALL live memory nodes of one student (status-quo
        node semantics; the repo protocol has no edge-delete path, and
        retrieval is node-based — see ADR for the honest limitation)."""
        service = self._require_memory()
        nodes = await service.list(student_id)
        deleted = 0
        for node in nodes:
            if await service.delete(student_id, node.memory_id):
                deleted += 1
        summary = {"memories_soft_deleted": deleted}
        _log_summary("purge_personal_memory", summary)
        return summary

    # ------------------------------------------------------- derived index

    async def rebuild_derived_indexes(self, student_id: str) -> dict[str, dict[str, Any]]:
        """Rebuild the DERIVED embedding indexes from the chunk FACTS
        (invariant E: chunks → vectors; never re-import user files).

        Uses the existing ``DocumentIndexManager`` contract with
        ``force=True``. With no backend (or no manager) every document is
        honestly marked ``unavailable`` — never faked, never raises.
        """
        repository = self._require_document_repository()
        docs = await repository.list_documents(student_id)
        results: dict[str, dict[str, Any]] = {}
        if self._index is None:
            reason = "index manager not configured"
            for doc in docs:
                results[str(doc.document_id)] = {
                    "status": "unavailable",
                    "reason": reason,
                    "index_version": None,
                }
            _log_summary(
                "rebuild_derived_indexes",
                {"doc_count": len(docs), "rebuilt": 0, "unavailable": len(docs)},
            )
            return results
        if not self._index.backend_available():
            reason = "no embedding backend provisioned"
            for doc in docs:
                results[str(doc.document_id)] = {
                    "status": "unavailable",
                    "reason": reason,
                    "index_version": None,
                }
            _log_summary(
                "rebuild_derived_indexes",
                {"doc_count": len(docs), "rebuilt": 0, "unavailable": len(docs)},
            )
            return results
        rebuilt = 0
        unavailable = 0
        no_chunks = 0
        for doc in docs:
            chunks = await repository.list_chunks(student_id, doc.document_id)
            if not chunks:
                results[str(doc.document_id)] = {
                    "status": "no_chunks",
                    "reason": "no chunk facts to rebuild from",
                    "index_version": None,
                }
                no_chunks += 1
                continue
            try:
                record = await self._index.build_index(
                    student_id, doc.document_id, force=True
                )
                results[str(doc.document_id)] = {
                    "status": "rebuilt",
                    "index_version": record.index_version if record is not None else None,
                }
                rebuilt += 1
            except EmbeddingUnavailableError as error:
                results[str(doc.document_id)] = {
                    "status": "unavailable",
                    "reason": str(error),
                    "index_version": None,
                }
                unavailable += 1
        _log_summary(
            "rebuild_derived_indexes",
            {
                "doc_count": len(docs),
                "rebuilt": rebuilt,
                "unavailable": unavailable,
                "no_chunks": no_chunks,
            },
        )
        return results

    # ---------------------------------------------------- educational history

    async def delete_educational_history(self, student_id: str) -> dict[str, Any]:
        """Delete one student's educational RESULT facts, then REPLAY the
        projection (invariant B — never a hardcoded mastery reset).

        Deleted (hard, inside ONE short transaction): mastery_evidence,
        misconception_observations, attempt_assessments, attempts,
        attempt_submissions, and attempt-linked verification_logs
        (candidate-linked logs are content authority and survive).

        Kept (session skeleton / authority records — deliberately NOT
        deleted): tutoring_cycles, cycle_transitions, problem_submissions,
        tutor_actions, assistance_issuances, practice_offers, outbox.

        After the deletes the StudentState projection is recomputed from
        the REMAINING evidence + observations via ``project_student_state``
        and persisted with ``upsert_student_state`` (stale projection row
        removed first — the projection is DERIVED, so replace-by-replay is
        the honest path). Whatever the replay yields IS the new state:
        with all evidence gone that is the estimator's natural baseline,
        computed by the replay itself. Idempotent: a second call deletes
        nothing, replays the same empty history, persists the same row.
        """
        uow = self._require_uow()
        async with uow.transaction() as conn:
            attempt_ids = [
                str(row[0])
                for row in (
                    await conn.execute(
                        select(attempts.c.attempt_id).where(
                            attempts.c.student_id == student_id
                        )
                    )
                ).all()
            ]

            deleted_by_table: dict[str, int] = {}
            # Facts and all v2 derived state disappear in the SAME authorized transaction.
            from sqlalchemy.dialects.sqlite import insert
            from mathtutor.application.learning_profile import revoke_pending
            await revoke_pending(conn, student_id)
            await conn.execute(insert(learning_generations).values(student_id=student_id, generation=1)
                .on_conflict_do_update(index_elements=["student_id"], set_={"generation": learning_generations.c.generation + 1}))
            for table in (learning_predictions, student_state_snapshots, learning_events, practice_feedback, initial_assessments):
                result = await conn.execute(sa_delete(table).where(table.c.student_id == student_id))
                deleted_by_table[table.name] = result.rowcount
            teaching_rows = (await conn.execute(select(teaching_contexts).where(
                teaching_contexts.c.student_id == student_id))).all()
            cleared_contexts = 0
            for row in teaching_rows:
                payload = _clear_teaching_results(row.payload)
                if payload != row.payload:
                    from datetime import datetime, timezone
                    await conn.execute(teaching_contexts.update().where(
                        teaching_contexts.c.student_id == student_id,
                        teaching_contexts.c.cycle_id == row.cycle_id,
                    ).values(payload=payload, updated_at=datetime.now(timezone.utc).isoformat()))
                    cleared_contexts += 1
            # FK order: evidence → observations → assessments → (attempt-linked
            # verification logs) → attempts → attempt submissions.
            for table in (mastery_evidence, misconception_observations):
                result = await conn.execute(
                    sa_delete(table).where(table.c.student_id == student_id)
                )
                deleted_by_table[table.name] = result.rowcount
            if attempt_ids:
                result = await conn.execute(
                    sa_delete(attempt_assessments).where(
                        attempt_assessments.c.attempt_id.in_(attempt_ids)
                    )
                )
                deleted_by_table[attempt_assessments.name] = result.rowcount
                result = await conn.execute(
                    sa_delete(verification_logs).where(
                        verification_logs.c.attempt_id.in_(attempt_ids)
                    )
                )
                deleted_by_table[verification_logs.name] = result.rowcount
            result = await conn.execute(
                sa_delete(attempts).where(attempts.c.student_id == student_id)
            )
            deleted_by_table[attempts.name] = result.rowcount
            result = await conn.execute(
                sa_delete(attempt_submissions).where(
                    attempt_submissions.c.student_id == student_id
                )
            )
            deleted_by_table[attempt_submissions.name] = result.rowcount
            total_deleted = sum(deleted_by_table.values())

            projection = await sqlite_education.load_student_projection(conn, student_id)
            if total_deleted == 0 and projection is None:
                summary: dict[str, Any] = {
                    "deleted_rows": 0,
                    "by_table": deleted_by_table,
                    "kept_skeleton_tables": list(EDUCATIONAL_SKELETON_KEPT),
                    "projection": None,
                    "teaching_contexts_cleared": cleared_contexts,
                }
                _log_summary("delete_educational_history", summary)
                return summary

            # Replay from the REMAINING evidence (empty after a full wipe) —
            # the projection is what it is; no value is written by hand.
            evidence = await sqlite_education.load_evidence_for_student(conn, student_id)
            observations = await sqlite_education.load_misconception_observations_for_student(
                conn, student_id
            )
            replay = project_student_state(
                student_id=student_uuid(student_id),
                evidence=evidence,
                observations=observations,
            )
            if projection is not None:
                await conn.execute(
                    sa_delete(student_state_projections).where(
                        student_state_projections.c.student_id == student_id
                    )
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
            summary = {
                "deleted_rows": total_deleted,
                "by_table": deleted_by_table,
                "kept_skeleton_tables": list(EDUCATIONAL_SKELETON_KEPT),
                "teaching_contexts_cleared": cleared_contexts,
                "projection": {
                    "projection_version": replay.projection_version,
                    "estimator_version": replay.estimator_version,
                    "evidence_remaining": len(evidence),
                    "observations_remaining": len(observations),
                },
            }
            _log_summary("delete_educational_history", summary)
            return summary


__all__ = [
    "CATEGORY_AUTHORITY_EDUCATIONAL",
    "CATEGORY_DERIVED",
    "CATEGORY_SECRET",
    "CATEGORY_SYSTEM",
    "CATEGORY_USER_CONTROLLED",
    "DATA_CATEGORIES",
    "DATA_CATEGORY_REASONS",
    "DATA_CATEGORY_VALUES",
    "EDUCATIONAL_RESULT_PARTIAL_TABLES",
    "EDUCATIONAL_RESULT_TABLES",
    "EDUCATIONAL_SKELETON_KEPT",
    "DataLifecycleService",
    "LifecycleUnavailableError",
    "SECRET_FIELD_FRAGMENTS",
    "SENSITIVE_FIELD_FRAGMENTS",
    "classify_field",
    "classify_table",
    "sanitize_summary",
]

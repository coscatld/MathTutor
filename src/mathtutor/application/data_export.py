"""Student data export — whitelist-only, user-comprehensible projections.

Phase 6 round 2 (SUBAGENT D). ``build_student_export`` assembles the export
body from EXISTING projection functions only — it never copies projection
logic into a second place:

- documents: the public document projection (``_project_document``, the
  single source in the desktop API layer — reused by lazy import);
- memory: the public memory projection (``_project_memory``, same reuse);
- student summary: the v2 EvidenceTracker's attributable counts. Legacy
  evidence with unavailable exposure chronology is explicitly uncertain;
  the old fixed-level mastery percentage is never exported as knowledge.

Structural guarantee: every field in the export body must appear in
``EXPORT_ALLOWED_FIELDS`` (per-section whitelist); ``validate_export``
refuses (raises) any field outside the whitelist. Secret/credential,
attestation, verification trace, reasoning, raw payload, storage paths and
hashes therefore CANNOT appear — they are not whitelisted, and the
projectors never emit them. Export operations log only sanitized counts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select

from mathtutor.application.document_ingestion import (
    DocumentIngestionService,
)
from mathtutor.application.personal_memory_service import (
    PersonalMemoryService,
)
from mathtutor.domain.documents import UserDocument
from mathtutor.domain.memory import PersonalMemoryNode
from mathtutor.infrastructure.observability import sanitize_for_logs
from mathtutor.infrastructure.schema import attempts
from mathtutor.repositories import sqlite_education
from mathtutor.repositories.uow import MathTutorUow

logger = logging.getLogger(__name__)

EXPORT_SCHEMA_VERSION = "mt-export-v2"

#: Explicit per-section field whitelist. Anything outside it is REFUSED.
#: (documents/memory mirror the existing public projections; the student
#: summary carries only the persisted projection's user-comprehensible
#: fields. No hash, no storage path, no attestation, no payload — ever.)
EXPORT_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "meta": frozenset({"schema_version", "exported_at", "student_id"}),
    "documents": frozenset(
        {
            "document_id",
            "filename",
            "mime_type",
            "status",
            "retrieval_enabled",
            "size_bytes",
            "page_count",
            "chunk_count",
            "image_count",
            "empty_page_count",
            "parse_warning",
            "created_at",
            "error",
        }
    ),
    "memory": frozenset(
        {
            "memory_id",
            "memory_type",
            "subject",
            "predicate",
            "object_json",
            "source_type",
            "confidence",
            "retrieval_enabled",
            "created_at",
            "updated_at",
        }
    ),
    "student_summary": frozenset(
        {
            "total_attempts",
            "estimator_version",
            "projection_version",
            "skills",
            "active_misconceptions",
            "model_status",
        }
    ),
    "student_summary.skills": frozenset({"skill_id", "evidence_status", "evidence_summary"}),
    "student_summary.skills.evidence_summary": frozenset({"independent", "assisted", "post_solution", "diagnostic", "ungradable", "step_correct", "joint_task_evidence", "duplicate_responses"}),
    "student_summary.skills.binary_counts": frozenset({"correct", "incorrect"}),
    "student_summary.active_misconceptions": frozenset(
        {"rule_id", "status", "confidence"}
    ),
}


class ExportValidationError(ValueError):
    """A field outside the export whitelist was found (fail closed)."""


def validate_export(export: dict[str, Any]) -> None:
    """Refuse any export whose fields escape the per-section whitelist."""
    for section in ("meta", "documents", "memory", "student_summary"):
        if section not in export:
            raise ExportValidationError(f"导出缺少分区: {section!r}")
    for key in export:
        if key not in {"meta", "documents", "memory", "student_summary"}:
            raise ExportValidationError(f"导出分区不在白名单: {key!r}")

    def _check(entry: Any, allowed: frozenset[str], where: str) -> None:
        if not isinstance(entry, dict):
            raise ExportValidationError(f"{where} 必须是对象")
        for field in entry:
            if field not in allowed:
                raise ExportValidationError(
                    f"字段 {where}.{field!r} 不在导出白名单（拒绝导出）"
                )

    _check(export["meta"], EXPORT_ALLOWED_FIELDS["meta"], "meta")
    _check(
        export["student_summary"],
        EXPORT_ALLOWED_FIELDS["student_summary"],
        "student_summary",
    )
    for index, entry in enumerate(export["documents"]):
        _check(entry, EXPORT_ALLOWED_FIELDS["documents"], f"documents[{index}]")
    for index, entry in enumerate(export["memory"]):
        _check(entry, EXPORT_ALLOWED_FIELDS["memory"], f"memory[{index}]")
    for index, entry in enumerate(export["student_summary"]["skills"]):
        _check(
            entry,
            EXPORT_ALLOWED_FIELDS["student_summary.skills"],
            f"student_summary.skills[{index}]",
        )
        counts = entry.get("evidence_summary", {})
        where = f"student_summary.skills[{index}].evidence_summary"
        _check(counts, EXPORT_ALLOWED_FIELDS["student_summary.skills.evidence_summary"], where)
        for key, value in counts.items():
            if key in {"independent", "assisted", "post_solution", "diagnostic"}:
                _check(value, EXPORT_ALLOWED_FIELDS["student_summary.skills.binary_counts"], f"{where}.{key}")
                if any(type(number) is not int or number < 0 for number in value.values()):
                    raise ExportValidationError("学习证据必须是非负整数计数")
            elif type(value) is not int or value < 0:
                raise ExportValidationError("学习证据必须是非负整数计数")
    for index, entry in enumerate(export["student_summary"]["active_misconceptions"]):
        _check(
            entry,
            EXPORT_ALLOWED_FIELDS["student_summary.active_misconceptions"],
            f"student_summary.active_misconceptions[{index}]",
        )


def _default_document_projector() -> Callable[[UserDocument], dict[str, Any]]:
    """The single existing public document projection (reused, never copied)."""
    from mathtutor.api.desktop_api import _project_document

    return _project_document  # type: ignore[return-value]


def _default_memory_projector() -> Callable[[PersonalMemoryNode], dict[str, Any]]:
    """The single existing public memory projection (reused, never copied)."""
    from mathtutor.api.desktop_api import _project_memory

    return _project_memory  # type: ignore[return-value]


async def build_student_export(
    *,
    student_id: str,
    documents: DocumentIngestionService,
    memory: PersonalMemoryService,
    uow: MathTutorUow,
    document_projector: Callable[[UserDocument], dict[str, Any]] | None = None,
    memory_projector: Callable[[PersonalMemoryNode], dict[str, Any]] | None = None,
    student_summary_loader: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Assemble the whitelist-validated export for one student.

    Reads live data only (repositories enforce ``deleted_at IS NULL``).
    ``validate_export`` runs BEFORE returning — an unexpected field fails
    the whole export (fail closed, never a silently partial export).
    """
    project_doc = document_projector or _default_document_projector()
    project_memory = memory_projector or _default_memory_projector()

    docs = await documents.list_documents(student_id)
    nodes = await memory.list(student_id)

    async def default_summary(sid: str) -> dict[str, Any]:
        return await export_evidence_summary(sid, uow=uow)

    summary_loader = student_summary_loader or default_summary
    summary = await summary_loader(student_id)

    export: dict[str, Any] = {
        "meta": {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "student_id": student_id,
        },
        "documents": [project_doc(doc) for doc in docs],
        "memory": [project_memory(node) for node in nodes],
        "student_summary": summary,
    }
    validate_export(export)

    log_summary = sanitize_for_logs(
        "export_summary",
        {
            "doc_count": len(docs),
            "memory_count": len(nodes),
            "attempt_count": summary.get("total_attempts", 0),
        },
    )
    logger.info("student export built: %s", log_summary)
    return export


async def export_evidence_summary(student_id, *, uow=None, student_state=None):
    """Shared API/export projection; strictly read-only, no migration writes."""
    from mathtutor.learning.knowledge_tracing.service import StudentStateService
    if uow is None:
        snapshot = await student_state.summary(student_id) if student_state else {"skills": [], "last_event_seq": 0}
        return {"total_attempts": sum(snapshot.get("totals", {}).values()), "estimator_version": "evidence_tracker_v2",
                "projection_version": snapshot["last_event_seq"], "skills": _export_skills(snapshot["skills"]),
                "active_misconceptions": [], "model_status": snapshot.get("dkt_mode", "not_trained")}
    tracker = student_state or StudentStateService(uow.engine)
    async with uow.transaction() as conn:
        snapshot = await tracker.summary(student_id, conn=conn)
        events = await tracker.events(student_id, conn=conn)
        known_attempts = {e.attempt_id for e in events if e.event_type == "attempt_assessed"}
        total_attempts = int((await conn.execute(select(func.count()).select_from(attempts).where(
            attempts.c.student_id == student_id))).scalar() or 0)
        legacy = await sqlite_education.load_evidence_for_student(conn, student_id)
        projection = await sqlite_education.load_student_projection(conn, student_id)
    rows = {row["skill_id"]: row for row in _export_skills(snapshot["skills"])}
    # Exporting cannot silently migrate. If a legacy import has not happened,
    # expose only the known observation count with uncertain provenance.
    for fact in legacy:
        if str(fact.attempt_id) in known_attempts:
            continue
        row = rows.setdefault(fact.skill_id, {"skill_id": fact.skill_id, "evidence_status": "历史帮助来源不完整，仍需确认",
            "evidence_summary": {"independent": {"correct": 0, "incorrect": 0},
                "assisted": {"correct": 0, "incorrect": 0}, "post_solution": {"correct": 0, "incorrect": 0},
                "diagnostic": {"correct": 0, "incorrect": 0}, "ungradable": 0,
                "step_correct": 0, "joint_task_evidence": 0, "duplicate_responses": 0}})
        row["evidence_summary"]["ungradable"] += 1
    return {"total_attempts": total_attempts, "estimator_version": "evidence_tracker_v2",
            "projection_version": snapshot["last_event_seq"], "skills": [rows[k] for k in sorted(rows)],
            "active_misconceptions": [{"rule_id": item["rule_id"], "status": item.get("status"), "confidence": None}
                for item in (projection or {}).get("active_misconceptions", ()) if isinstance(item, dict) and "rule_id" in item],
            "model_status": snapshot.get("dkt_mode", "not_trained")}


def _export_skills(rows):
    return [{"skill_id": row["skill_id"], "evidence_status": row["evidence_status"],
             "evidence_summary": {key: value for key, value in row["evidence_summary"].items()
                                  if key in EXPORT_ALLOWED_FIELDS["student_summary.skills.evidence_summary"]}}
            for row in rows]


__all__ = [
    "EXPORT_ALLOWED_FIELDS",
    "EXPORT_SCHEMA_VERSION",
    "ExportValidationError",
    "build_student_export",
    "export_evidence_summary",
    "validate_export",
]

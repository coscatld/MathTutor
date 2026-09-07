"""Student data export — whitelist-only, user-comprehensible projections.

Phase 6 round 2 (SUBAGENT D). ``build_student_export`` assembles the export
body from EXISTING projection functions only — it never copies projection
logic into a second place:

- documents: the public document projection (``_project_document``, the
  single source in the desktop API layer — reused by lazy import);
- memory: the public memory projection (``_project_memory``, same reuse);
- student summary: the PERSISTED StudentState projection row (computed at
  write time by ``learning.projection.project_student_state``) read back via
  the existing ``load_student_projection`` + the attempt count — no
  re-projection and no duplicated display formatting.

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

EXPORT_SCHEMA_VERSION = "mt-export-v1"

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
        }
    ),
    "student_summary.skills": frozenset({"skill_id", "mastery"}),
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
        if key not in EXPORT_ALLOWED_FIELDS:
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
        async with uow.transaction() as conn:
            projection = await sqlite_education.load_student_projection(conn, sid)
            total = await conn.execute(
                select(func.count())
                .select_from(attempts)
                .where(attempts.c.student_id == sid)
            )
            total_attempts = int(total.scalar() or 0)
        if projection is None:
            return {
                "total_attempts": total_attempts,
                "estimator_version": "",
                "projection_version": None,
                "skills": [],
                "active_misconceptions": [],
            }
        skills = [
            {"skill_id": item["skill_id"], "mastery": item["mastery"]}
            for item in projection.get("skill_mastery") or []
            if isinstance(item, dict) and "skill_id" in item
        ]
        misconceptions = [
            {
                "rule_id": item["rule_id"],
                "status": item.get("status"),
                "confidence": item.get("confidence"),
            }
            for item in projection.get("active_misconceptions") or []
            if isinstance(item, dict) and "rule_id" in item
        ]
        return {
            "total_attempts": total_attempts,
            "estimator_version": projection.get("estimator_version") or "",
            "projection_version": projection.get("projection_version"),
            "skills": skills,
            "active_misconceptions": misconceptions,
        }

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


__all__ = [
    "EXPORT_ALLOWED_FIELDS",
    "EXPORT_SCHEMA_VERSION",
    "ExportValidationError",
    "build_student_export",
    "validate_export",
]

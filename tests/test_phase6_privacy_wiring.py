"""MAIN INTEGRATION 4 (Phase 6 round 2): the privacy / data-lifecycle
surfaces wired into the product.

- the existing DELETE document/memory endpoints now run through
  DataLifecycleService: document deletion really removes chunk facts +
  derived vectors/index rows + the storage file; memory deletion keeps the
  status-quo soft-delete semantics;
- POST /privacy/purge-documents + /privacy/purge-memory wipe one student's
  USER_CONTROLLED data wholesale, touching no other student;
- POST /privacy/educational-history deletes the educational RESULT facts
  and REPLAYS the StudentState projection (invariant B — mastery is never
  zeroed by hand; the summary reads null for unobserved skills again);
  it never touches personal memory, and is idempotent; in-memory mode
  fails closed with 409;
- POST /privacy/rebuild-indexes rebuilds DERIVED indexes from chunk facts,
  honestly marking ``unavailable`` without a backend (invariant E/G);
- GET /privacy/export returns ONLY whitelisted, user-comprehensible
  projections — secret/attestation/trace/payload/path/hash fields cannot
  appear (fail closed via validate_export).
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import (
    get_product_state,
    reset_product_state,
)
from mathtutor.application.desktop_files import PickedFile
from mathtutor.security.scopes import DEV_STUDENT_ID
from mathtutor.security.settings import MathTutorSecuritySettings

pytestmark = pytest.mark.asyncio

_FORBIDDEN_EXPORT_FRAGMENTS = (
    "attestation",
    "hash",
    "payload",
    "raw_text",
    "secret",
    "storage_ref",
    "reasoning",
    "trace",
    "vector",
)


def _client(db_file: Path | None = None) -> TestClient:
    settings = MathTutorSecuritySettings(environment="development", host="127.0.0.1")
    return TestClient(
        create_math_tutor_app(
            settings,
            auth_enabled=False,
            db_path=None if db_file is None else str(db_file),
        )
    )


def _collect(ws) -> list[dict]:
    events: list[dict] = []
    while True:
        frame = json.loads(ws.receive_text())
        events.append(frame)
        if frame.get("event_type") == "turn_end":
            break
    return events


def _submit_solved_problem(client, text: str, answer: str, session_id: str) -> None:
    """One solved attempt through the real WS (different session per context —
    reusing a session id restores the existing session instead of starting
    a new cycle)."""
    with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "command": "submit_problem",
                    "payload": {"text": text},
                    "session_id": session_id,
                }
            )
        )
        _collect(ws)
        ws.send_text(
            json.dumps(
                {
                    "command": "submit_attempt",
                    "payload": {"answer": answer},
                    "session_id": session_id,
                }
            )
        )
        _collect(ws)


async def _ingest_document(state, name: str, content: bytes):
    picked = PickedFile(
        filename=name,
        mime_type="text/plain",
        data=content,
        original_path="",
    )
    return await state.documents.ingest(str(DEV_STUDENT_ID), picked)


async def _table_rows(state, table_name: str) -> int:
    import sqlalchemy as sa

    async with state.uow.transaction() as conn:
        return len((await conn.execute(sa.text(f"SELECT * FROM {table_name}"))).all())


async def _row_values(state, table_name: str, column: str) -> list:
    import sqlalchemy as sa

    async with state.uow.transaction() as conn:
        return [
            row[0]
            for row in (
                await conn.execute(sa.text(f"SELECT {column} FROM {table_name}"))
            ).all()
        ]


def _assert_no_forbidden_fields(node, where: str) -> None:
    """Recursively refuse secret/attestation/payload-class keys in the export."""
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = str(key).lower().replace("-", "_")
            for fragment in _FORBIDDEN_EXPORT_FRAGMENTS:
                assert fragment not in normalized, f"{where}.{key} 含敏感字段"
            _assert_no_forbidden_fields(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _assert_no_forbidden_fields(item, f"{where}[{index}]")


async def test_delete_document_endpoint_cleans_chunks_vectors_and_file(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        state = get_product_state(db_file)
        doc = await _ingest_document(state, "notes.txt", b"hello world " * 8)
        chunks = await state.document_repository.list_chunks(
            str(DEV_STUDENT_ID), doc.document_id
        )
        assert len(chunks) >= 1, "ingest must produce chunk facts"
        storage_ref = doc.storage_ref
        assert await state.document_storage.exists(storage_ref)

        response = client.delete(
            f"/api/v2/math-tutor/desktop/documents/{doc.document_id}"
        )
        assert response.status_code == 200
        assert response.json() == {"deleted": True}

        # Chunk facts + derived vectors + index-build rows are really gone.
        assert (
            await state.document_repository.list_chunks(
                str(DEV_STUDENT_ID), doc.document_id
            )
            == []
        )
        assert await _table_rows(state, "document_chunks") == 0
        assert await _table_rows(state, "document_chunk_vectors") == 0
        assert await _table_rows(state, "document_index_builds") == 0
        # Storage file removed (no trash — immediate cleanup, status quo).
        assert not await state.document_storage.exists(storage_ref)
        # The row is soft-deleted (tombstone kept, immediately invisible).
        listed = await state.documents.list_documents(str(DEV_STUDENT_ID))
        assert doc.document_id not in {d.document_id for d in listed}
        assert await _table_rows(state, "user_documents") == 1
    reset_product_state()


async def test_purge_documents_endpoint_wipes_only_this_student(tmp_path: Path) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        state = get_product_state(db_file)
        doc_a = await _ingest_document(state, "a.txt", b"aaaa " * 8)
        await _ingest_document(state, "b.txt", b"bbbb " * 8)
        other = uuid4().hex
        await _ingest_document(state, "other.txt", b"cccc " * 8)
        # A second student's document must survive untouched.
        other_picked = PickedFile(
            filename="other-student.txt",
            mime_type="text/plain",
            data=b"dddd " * 8,
            original_path="",
        )
        other_doc = await state.documents.ingest(other, other_picked)

        response = client.post("/api/v2/math-tutor/desktop/privacy/purge-documents")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["documents_soft_deleted"] >= 1
        assert body["chunks_removed"] >= 2
        assert body["storage_files_removed"] >= 2

        assert await _table_rows(state, "document_chunks") == 1  # only the other student's
        other_chunks = await state.document_repository.list_chunks(other, other_doc.document_id)
        assert len(other_chunks) >= 1
        listed = await state.documents.list_documents(str(DEV_STUDENT_ID))
        assert listed == []
        other_listed = await state.documents.list_documents(other)
        assert [d.document_id for d in other_listed] == [other_doc.document_id]
    reset_product_state()


async def test_delete_memory_endpoint_keeps_status_quo_soft_delete(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        state = get_product_state(db_file)
        node = await state.personal_memory.add_explicit(
            str(DEV_STUDENT_ID),
            memory_type="interest",
            subject="数学",
            predicate="喜欢",
            object_json={"value": "应用题"},
        )

        response = client.delete(
            f"/api/v2/math-tutor/desktop/memory/{node.memory_id}"
        )
        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        listed = await state.personal_memory.list(str(DEV_STUDENT_ID))
        assert node.memory_id not in {n.memory_id for n in listed}

        # purge clears the rest (status-quo soft delete, no trash).
        await state.personal_memory.add_explicit(
            str(DEV_STUDENT_ID),
            memory_type="interest",
            subject="几何",
            predicate="喜欢",
            object_json={},
        )
        response = client.post("/api/v2/math-tutor/desktop/privacy/purge-memory")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["memories_soft_deleted"] >= 1
        assert await state.personal_memory.list(str(DEV_STUDENT_ID)) == []
    reset_product_state()


async def test_educational_history_endpoint_deletes_facts_and_replays_projection(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        state = get_product_state(db_file)
        _submit_solved_problem(client, "2x + 3 = 7", "2", "privacy-wiring-a")
        _submit_solved_problem(client, "5 + 3", "8", "privacy-wiring-b")

        assert await _table_rows(state, "attempts") == 2
        assert await _table_rows(state, "mastery_evidence") >= 2
        assert await _table_rows(state, "attempt_assessments") == 2

        response = client.post("/api/v2/math-tutor/desktop/privacy/educational-history")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["deleted_rows"] >= 6  # evidence×2 + assessments×2 + attempts×2 + subs
        assert body["by_table"]["attempts"] == 2
        assert body["by_table"]["mastery_evidence"] >= 2
        assert body["projection"]["evidence_remaining"] == 0
        assert "tutoring_cycles" in body["kept_skeleton_tables"]

        # Facts are gone; the session skeleton survives.
        assert await _table_rows(state, "attempts") == 0
        assert await _table_rows(state, "mastery_evidence") == 0
        assert await _table_rows(state, "misconception_observations") == 0
        assert await _table_rows(state, "attempt_assessments") == 0
        assert await _table_rows(state, "tutoring_cycles") >= 1
        assert await _table_rows(state, "math_problems") >= 1

        # The projection was REPLAYED (persisted), not hand-zeroed: the
        # student-summary now reads mastery=null for every skill (no
        # observation), which is the replay's natural result.
        summary = client.get("/api/v2/math-tutor/desktop/student-summary").json()
        assert summary["total_attempts"] == 0
        assert all(skill["mastery"] is None for skill in summary["skills"])

        # Idempotent: a second call deletes nothing and replays the same.
        response = client.post("/api/v2/math-tutor/desktop/privacy/educational-history")
        assert response.status_code == 200
        assert response.json()["deleted_rows"] == 0
        summary_again = client.get(
            "/api/v2/math-tutor/desktop/student-summary"
        ).json()
        assert summary_again == summary
    reset_product_state()


async def test_educational_history_never_touches_personal_memory(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        state = get_product_state(db_file)
        node = await state.personal_memory.add_explicit(
            str(DEV_STUDENT_ID),
            memory_type="interest",
            subject="数学",
            predicate="喜欢",
            object_json={},
        )
        _submit_solved_problem(client, "x/2 = 3", "6", "privacy-wiring-c")

        response = client.post("/api/v2/math-tutor/desktop/privacy/educational-history")
        assert response.status_code == 200
        # Memory is USER_CONTROLLED — a different class, a different surface.
        listed = await state.personal_memory.list(str(DEV_STUDENT_ID))
        assert [n.memory_id for n in listed] == [node.memory_id]
        assert await _table_rows(state, "attempts") == 0
    reset_product_state()


async def test_educational_history_in_memory_mode_fails_closed() -> None:
    reset_product_state()
    with _client(None) as client:
        response = client.post("/api/v2/math-tutor/desktop/privacy/educational-history")
        assert response.status_code == 409
    reset_product_state()


async def test_rebuild_indexes_marks_unavailable_without_backend(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        state = get_product_state(db_file)
        doc = await _ingest_document(state, "notes.txt", b"hello world " * 8)
        response = client.post("/api/v2/math-tutor/desktop/privacy/rebuild-indexes")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        entry = body["documents"][str(doc.document_id)]
        assert entry["status"] == "unavailable", "no backend → honest unavailable"
        assert entry["index_version"] is None
    reset_product_state()


async def test_export_returns_only_whitelisted_user_data(tmp_path: Path) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        state = get_product_state(db_file)
        await _ingest_document(state, "notes.txt", b"export test " * 8)
        await state.personal_memory.add_explicit(
            str(DEV_STUDENT_ID),
            memory_type="interest",
            subject="数学",
            predicate="喜欢",
            object_json={"value": "应用题"},
        )
        _submit_solved_problem(client, "2x + 3 = 7", "2", "privacy-wiring-d")

        response = client.get("/api/v2/math-tutor/desktop/privacy/export")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"meta", "documents", "memory", "student_summary"}
        assert body["meta"]["schema_version"] == "mt-export-v2"
        assert len(body["documents"]) == 1
        assert body["documents"][0]["filename"] == "notes.txt"
        assert len(body["memory"]) == 1
        assert body["memory"][0]["subject"] == "数学"
        assert body["student_summary"]["total_attempts"] == 1
        assert len(body["student_summary"]["skills"]) >= 1
        assert all("mastery" not in row for row in body["student_summary"]["skills"])
        _assert_no_forbidden_fields(body, "export")
    reset_product_state()


async def test_export_in_memory_mode_returns_empty_summary() -> None:
    reset_product_state()
    with _client(None) as client:
        response = client.get("/api/v2/math-tutor/desktop/privacy/export")
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["schema_version"] == "mt-export-v2"
        assert body["documents"] == []
        assert body["memory"] == []
        assert body["student_summary"] == {
            "total_attempts": 0,
            "estimator_version": "evidence_tracker_v2",
            "projection_version": 0,
            "skills": [],
            "active_misconceptions": [],
            "item_error_observations": [],
            "model_status": "not_trained",
        }
    reset_product_state()

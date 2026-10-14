#!/usr/bin/env python3
"""Seed or verify one persistent MathTutor profile during a DMG upgrade test.

The wrapper executes this file with each artifact's bundled Python and
``PYTHONPATH`` rooted only at that artifact.  The harness may live in the
checkout; every product import and runtime dependency comes from the mounted
artifact.  Reports contain IDs/counts/hashes only, never document or memory
values.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID


SESSION_ID = "rc-upgrade-session"
DOCUMENT_MARKER = "RC_UPGRADE_DOCUMENT_SENTINEL LINEAR_EQUATION"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=")


def learning_fingerprint(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM learning_events ORDER BY student_id,event_seq").fetchall()
    return {"count": len(rows), "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def _collect(ws) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        frame = json.loads(ws.receive_text())
        events.append(frame)
        if frame.get("event_type") == "turn_end":
            return events


def _turn(client, command: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        ws.send_text(
            json.dumps(
                {"command": command, "payload": payload, "session_id": SESSION_ID}
            )
        )
        return _collect(ws)


def _committed(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event_type") == "tutor_action_committed"]


def _client(db_path: Path, namespace: str):
    from fastapi.testclient import TestClient

    product_app = importlib.import_module(f"{namespace}.api.product_app")
    product_state = importlib.import_module(f"{namespace}.api.product_state")
    migrate = importlib.import_module(f"{namespace}.infrastructure.migrate")
    security_settings = importlib.import_module(f"{namespace}.security.settings")

    product_state.reset_product_state()
    migrate.upgrade_db(str(db_path))
    settings = security_settings.MathTutorSecuritySettings(
        environment="test", host="127.0.0.1"
    )
    return TestClient(
        product_app.create_math_tutor_app(
            settings, auth_enabled=False, db_path=str(db_path)
        )
    )


def seed(data_root: Path, output: Path, namespace: str) -> dict[str, Any]:
    db_path = data_root / "math_tutor.db"
    data_root.mkdir(parents=True, exist_ok=True)
    with _client(db_path, namespace) as client:
        document = client.post(
            "/api/v2/math-tutor/desktop/documents/import",
            files={
                "file": (
                    "upgrade-notes.txt",
                    f"{DOCUMENT_MARKER}：升级后仍可检索。".encode(),
                    "text/plain",
                )
            },
        )
        document.raise_for_status()
        memory = client.post(
            "/api/v2/math-tutor/desktop/memory",
            json={
                "memory_type": "learning_preference",
                "subject": "升级测试",
                "predicate": "偏好",
                "object_json": {"style": "stepwise"},
            },
        )
        memory.raise_for_status()

        problem_events = _turn(client, "submit_problem", {"text": "2x + 3 = 7"})
        attempt_events = _turn(client, "submit_attempt", {"answer": "2"})
        offer_event = next(
            event
            for event in _committed(attempt_events)
            if event.get("payload", {}).get("action") == "practice_offered"
        )
        offer_id = offer_event["extra"]["offer_id"]
        parent_cycle_id = offer_event["extra"]["parent_cycle_id"]
        parent_before = client.get(f"/api/v2/math-tutor/cycles/{parent_cycle_id}")
        parent_before.raise_for_status()
        parent_state = parent_before.json()["state"]
        accepted = _turn(client, "accept_practice_offer", {"offer_id": offer_id})
        started = next(
            event
            for event in _committed(accepted)
            if event.get("payload", {}).get("action") == "practice_started"
        )
        child_cycle_id = started["extra"]["child_cycle_id"]
        parent_after = client.get(f"/api/v2/math-tutor/cycles/{parent_cycle_id}")
        parent_after.raise_for_status()
        if parent_after.json()["state"] != parent_state:
            raise RuntimeError("accepting practice changed the parent's learning state")

        summary = client.get("/api/v2/math-tutor/desktop/student-summary")
        summary.raise_for_status()
        image = None
        if namespace == "mathtutor":
            import httpx
            gateway_module = importlib.import_module(f"{namespace}.infrastructure.generative_gateway")
            chat_module = importlib.import_module(f"{namespace}.infrastructure.tutor_chat")
            state_module = importlib.import_module(f"{namespace}.api.product_state")
            async def fixture_key():
                return "nonpersonal-upgrade-fixture"
            fixture_provider = gateway_module.OpenAICompatibleProvider(
                base_url="https://example.invalid/v1", model="gpt-4.1", provider_id="openai",
                api_key_resolver=fixture_key, transport=httpx.MockTransport(lambda request: httpx.Response(
                    200, json={"choices": [{"message": {"content": "这是升级测试图片。"}, "finish_reason": "stop"}]})))
            state = state_module.get_product_state()
            state.gateway.register_provider(gateway_module.ModelRole.TUTOR_WRITER, fixture_provider)
            state.controller.chat_responder = chat_module.TutorChatResponder(state.gateway)
            uploaded = client.post("/api/v2/math-tutor/images", files={"file": ("upgrade.png", PNG, "image/png")})
            uploaded.raise_for_status()
            image = uploaded.json()
            _turn(client, "send_message", {"text": "升级测试图片", "attachment_ids": [image["id"]]})
            if image["id"] not in json.dumps(client.get(f"/api/v2/math-tutor/sessions/{SESSION_ID}").json()):
                raise RuntimeError("old artifact did not persist the synthetic image message")
        backup = client.post("/api/v2/math-tutor/desktop/backup", json={})
        backup.raise_for_status()
        if backup.json().get("ok") is not True:
            raise RuntimeError("pre-RC backup creation failed")

        expected = {
            "schema_version": 1,
            "database": db_path.name,
            "document_id": document.json()["document_id"],
            "memory_id": memory.json()["memory_id"],
            "parent_cycle_id": parent_cycle_id,
            "parent_state": parent_state,
            "offer_id": offer_id,
            "child_cycle_id": child_cycle_id,
            "backup_name": backup.json()["backup"]["path"],
            "student_summary": summary.json(),
            "image": image,
            "learning_fingerprint": learning_fingerprint(db_path) if namespace == "mathtutor" else None,
            "problem_state_observed": any(
                event.get("cycle_state") == "awaiting_attempt"
                for event in _committed(problem_events)
            ),
        }
    output.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    return {"status": "PASS", "operation": "seed", "facts": expected}


async def _authority_checks(db_path: Path, offer_id: str) -> dict[str, Any]:
    from mathtutor.infrastructure.db import create_db_engine
    from mathtutor.learning.projection import project_student_state
    from mathtutor.repositories import sqlite_education
    from mathtutor.repositories.sqlite_practice import SQLitePracticeRepository
    from mathtutor.repositories.uow import MathTutorUow
    from mathtutor.security.scopes import DEV_STUDENT_ID, student_uuid

    engine = create_db_engine(db_path)
    try:
        uow = MathTutorUow(engine)
        repository = SQLitePracticeRepository(uow)
        offer = await repository.load_offer(UUID(offer_id))
        release = await repository.load_release(offer.exercise_release_id) if offer else None
        exact = await repository.load_exact_verified(release) if release else None
        async with uow.transaction() as connection:
            persisted = await sqlite_education.load_student_projection(
                connection, DEV_STUDENT_ID
            )
            evidence = await sqlite_education.load_evidence_for_student(
                connection, DEV_STUDENT_ID
            )
            observations = (
                await sqlite_education.load_misconception_observations_for_student(
                    connection, DEV_STUDENT_ID
                )
            )
        replay = project_student_state(
            student_id=student_uuid(DEV_STUDENT_ID),
            evidence=evidence,
            observations=observations,
        )
        def normalized(value: Any) -> Any:
            return json.loads(json.dumps(value, default=str))

        replay_matches = bool(persisted) and all(
            normalized(persisted[key]) == normalized(getattr(replay, key))
            for key in (
                "estimator_version",
                "projection_version",
                "concept_mastery",
                "skill_mastery",
                "active_misconceptions",
            )
        )
        return {
            "offer_resolves": offer is not None,
            "release_resolves": release is not None,
            "exact_verified_snapshot_resolves": exact is not None,
            "student_state_replay_consistent": replay_matches,
            "evidence_count": len(evidence),
            "projection_version": replay.projection_version,
        }
    finally:
        await engine.dispose()


def verify(data_root: Path, expected_path: Path, namespace: str) -> dict[str, Any]:
    expected = json.loads(expected_path.read_text())
    db_path = data_root / "math_tutor.db"
    with _client(db_path, namespace) as client:
        version = client.get("/version")
        version.raise_for_status()
        documents = client.get("/api/v2/math-tutor/desktop/documents")
        memories = client.get("/api/v2/math-tutor/desktop/memory")
        offers = client.get("/api/v2/math-tutor/offers")
        parent = client.get(
            f"/api/v2/math-tutor/cycles/{expected['parent_cycle_id']}"
        )
        child = client.get(
            f"/api/v2/math-tutor/cycles/{expected['child_cycle_id']}"
        )
        summary = client.get("/api/v2/math-tutor/desktop/student-summary")
        backup = client.post(
            "/api/v2/math-tutor/desktop/backup/verify",
            json={"path": expected["backup_name"]},
        )
        checks = {
            "migration_head": version.json().get("release_config", {}).get("migration_head")
            == "024",
            "document_survives": documents.status_code == 200
            and any(item["document_id"] == expected["document_id"] for item in documents.json()),
            "memory_survives": memories.status_code == 200
            and any(item["memory_id"] == expected["memory_id"] for item in memories.json()),
            "offer_survives": offers.status_code == 200
            and any(item["offer_id"] == expected["offer_id"] for item in offers.json()),
            "parent_state_preserved": parent.status_code == 200
            and parent.json().get("state") == expected["parent_state"],
            "child_cycle_survives": child.status_code == 200,
            "profile_available": summary.status_code == 200
            and summary.json().get("schema_version") == "learning_profile_v1"
            and summary.json().get("total_attempts", 0) > 0,
            "learning_events_preserved": (learning_fingerprint(db_path) == expected["learning_fingerprint"]
                if expected.get("learning_fingerprint") else True),
            "image_bytes_preserved": (client.get(expected["image"]["url"]).content == PNG
                if expected.get("image") else True),
            "backup_verifies": backup.status_code == 200
            and backup.json().get("ok") is True,
        }
        resume = client.post(f"/api/v2/math-tutor/offers/{expected['offer_id']}/resume")
        checks["continue_practice"] = resume.status_code == 200 and resume.json().get("session_id") == SESSION_ID
        if expected.get("image"):
            conversation = client.get(f"/api/v2/math-tutor/sessions/{SESSION_ID}").json()
            checks["image_message_preserved"] = expected["image"]["id"] in json.dumps(conversation)
    checks.update(asyncio.run(_authority_checks(db_path, expected["offer_id"])))
    # Erasure occurs only AFTER preservation/replay checks, against this generated
    # profile. The wrapper starts another artifact process to verify no recovery.
    preservation_passed = all(value is True for key, value in checks.items()
                             if not key.endswith("_count") and key != "projection_version")
    if preservation_passed:
        with _client(db_path, namespace) as client:
            deletion = client.post("/api/v2/math-tutor/desktop/privacy/educational-history")
            checks["delete_learning_history"] = deletion.status_code == 200
    required = [value for key, value in checks.items() if not key.endswith("_count") and key != "projection_version"]
    return {
        "status": "PASS" if all(value is True for value in required) else "FAIL",
        "operation": "verify",
        "checks": checks,
    }


def verify_deleted(data_root, expected_path, namespace):
    expected = json.loads(expected_path.read_text())
    db = data_root / "math_tutor.db"
    with _client(db, namespace) as client:
        summary = client.get("/api/v2/math-tutor/desktop/student-summary").json()
        evidence = client.get("/api/v2/math-tutor/desktop/student-evidence").json()
        offer = next(o for o in client.get("/api/v2/math-tutor/offers").json() if o["offer_id"] == expected["offer_id"])
        checks = {"no_learning_events_after_process_restart": learning_fingerprint(db)["count"] == 0,
                  "no_evidence_after_process_restart": evidence["items"] == [],
                  "empty_profile_after_process_restart": summary["coverage"]["observed_skills"] == 0,
                  "accepted_exercise_preserved": offer["status"] == "ACCEPTED" and offer["child_cycle_id"] == expected["child_cycle_id"],
                  "old_basis_unavailable": offer["basis"] is None and offer["evidence_ids"] == [],
                  "conversation_preserved": summary["has_conversations"]}
    return {"operation": "verify-deleted", "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("seed", "verify", "verify-deleted"))
    parser.add_argument(
        "--namespace",
        required=True,
        choices=("deeptutor.math_tutor", "mathtutor"),
        help="Artifact-local package namespace; the pre-RC seed uses the legacy name.",
    )
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    os.environ.update(
        {
            "MATHTUTOR_DB_PATH": str(args.data_root / "math_tutor.db"),
            "MATHTUTOR_DATA_ROOT": str(args.data_root),
            "MATHTUTOR_ENVIRONMENT": "test",
            "AUTH_ENABLED": "0",
            "MATHTUTOR_AUTH_ENABLED": "0",
        }
    )
    result = (
        seed(args.data_root, args.state, args.namespace)
        if args.operation == "seed"
        else (verify_deleted(args.data_root, args.state, args.namespace) if args.operation == "verify-deleted"
              else verify(args.data_root, args.state, args.namespace))
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

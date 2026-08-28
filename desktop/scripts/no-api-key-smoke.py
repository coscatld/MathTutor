#!/usr/bin/env python3
"""Packaged, network-free proof that core MathTutor works without an API key."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any


def collect(ws) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while True:
        frame = json.loads(ws.receive_text())
        frames.append(frame)
        if frame.get("event_type") == "turn_end":
            return frames


def turn(client, session: str, command: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        ws.send_text(json.dumps({"command": command, "payload": payload, "session_id": session}))
        return collect(ws)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    args.data_root.mkdir(parents=True, exist_ok=True)
    db_path = args.data_root / "math_tutor.db"
    os.environ.update(
        {
            "MATHTUTOR_DB_PATH": str(db_path),
            "MATHTUTOR_DATA_ROOT": str(args.data_root),
            "MATHTUTOR_ENVIRONMENT": "test",
            "AUTH_ENABLED": "0",
            "MATHTUTOR_AUTH_ENABLED": "0",
        }
    )

    from fastapi.testclient import TestClient

    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import get_product_state, reset_product_state
    from mathtutor.infrastructure.migrate import upgrade_db
    from mathtutor.release_probe import document_retrieval_probe
    from mathtutor.security.settings import MathTutorSecuritySettings

    reset_product_state()
    upgrade_db(str(db_path))
    app = create_math_tutor_app(
        MathTutorSecuritySettings(environment="test", host="127.0.0.1"),
        auth_enabled=False,
        db_path=str(db_path),
    )
    with TestClient(app) as client:
        readiness = client.get("/api/v2/math-tutor/desktop/readiness").json()
        settings = client.get("/api/v2/math-tutor/desktop/settings").json()
        imported = client.post(
            "/api/v2/math-tutor/desktop/documents/import",
            files={
                "file": (
                    "offline-notes.txt",
                    b"OFFLINE_LEXICAL_SENTINEL LINEAR_EQUATION",
                    "text/plain",
                )
            },
        )
        session = "no-api-key-smoke"
        problem = turn(client, session, "submit_problem", {"text": "2x + 3 = 7"})
        incorrect = turn(client, session, "submit_attempt", {"answer": "3"})
        correct = turn(client, session, "submit_attempt", {"answer": "2"})
        states = [
            frame.get("cycle_state")
            for frame in problem + incorrect + correct
            if frame.get("event_type") == "tutor_action_committed"
        ]
        offers = client.get("/api/v2/math-tutor/offers").json()
        summary = client.get("/api/v2/math-tutor/desktop/student-summary").json()
        state = get_product_state()
        runtime = {
            "gateway_roles": len(state.gateway.configured_roles()),
            "writer": type(state.capability.writer).__name__,
            "worker": client.get("/health").json().get("verifier") == "ok",
        }
    lexical = asyncio.run(
        document_retrieval_probe(db_path, "OFFLINE_LEXICAL_SENTINEL")
    )
    checks = {
        "no_provider_configured": settings.get("is_configured") is False
        and runtime["gateway_roles"] == 0,
        "readiness_degraded_not_blocked": readiness.get("status") == "DEGRADED"
        and readiness.get("checks", {}).get("gateway") == "degraded",
        "parser_solver_verifier_worker": runtime["worker"] is True
        and "awaiting_attempt" in states
        and "awaiting_retry" in states
        and "solved" in states,
        "attempt_verifier_student_model": summary.get("total_attempts") == 2,
        "template_tutor_writer": runtime["writer"] == "TemplateTutorWriter",
        "bank_template_practice": any(item.get("status") == "ACTIVE" for item in offers),
        "document_import": imported.status_code == 200,
        "document_lexical_retrieval": lexical == {"hit": True, "vector_used": False},
        "embedding_not_required": readiness.get("checks", {}).get("embedding") == "degraded",
    }
    result = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "facts": {
            "attempt_count": summary.get("total_attempts"),
            "offer_count": len(offers),
            "writer": runtime["writer"],
            "readiness": readiness.get("status"),
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

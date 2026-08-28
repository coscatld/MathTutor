"""MathTutorCapability end-to-end: envelope → state machine → services → events."""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus

from mathtutor.capabilities.math_tutor import MathTutorCapability
from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.verification_backend import (
    InProcessVerificationBackend,
    VerificationWorkerCrashedError,
)
from mathtutor.security.scopes import DEV_STUDENT_ID

pytestmark = pytest.mark.asyncio


class _EventRecorder:
    """Collects every event the capability emits on a shared bus."""

    def __init__(self) -> None:
        self.bus = StreamBus()
        self.events: list[dict[str, Any]] = []

    def start(self) -> None:
        import asyncio

        async def _collect() -> None:
            async for event in self.bus.subscribe():
                self.events.append(
                    {
                        "type": event.type,
                        "content": event.content,
                        "stage": event.stage,
                        "metadata": event.metadata or {},
                    }
                )

        self._task = asyncio.get_event_loop().create_task(_collect())

    async def stop(self) -> None:
        await self.bus.close()
        await self._task

    def contents(self) -> list[str]:
        return [e["content"] for e in self.events if e["type"] == "content"]

    def last_state(self) -> dict[str, Any]:
        states = [e["metadata"] for e in self.events if e["metadata"].get("cycle_state")]
        return states[-1] if states else {}


@pytest.fixture()
def capability() -> MathTutorCapability:
    return MathTutorCapability()


async def run_turn(capability: MathTutorCapability, session_id: str, message: str) -> tuple[list[str], dict[str, Any]]:
    recorder = _EventRecorder()
    recorder.start()
    context = UnifiedContext(
        session_id=session_id,
        user_message=message,
        active_capability="math_tutor",
    )
    await capability.run(context, recorder.bus)
    await recorder.stop()
    return recorder.contents(), recorder.last_state()


def envelope(command: str, payload: dict[str, Any], expected_version: int | None = None) -> str:
    body: dict[str, Any] = {"command": command, "payload": payload}
    if expected_version is not None:
        body["expected_cycle_version"] = expected_version
    return json.dumps(body, ensure_ascii=False)


class TestFullSolveFlow:
    async def test_submit_verify_attempt_correct(self, capability: MathTutorCapability) -> None:
        _, state = await run_turn(capability, "s1", envelope("submit_problem", {"text": "2x + 3 = 7"}))
        assert state["cycle_state"] == "awaiting_attempt"
        assert "verified" in state["detail"]
        assert "submit_attempt" in state["allowed_next_inputs"]
        assert "request_hint" in state["allowed_next_inputs"]

        # Wrong first, retry loop, then correct.
        _, state = await run_turn(capability, "s1", envelope("submit_attempt", {"answer": "3"}))
        assert state["cycle_state"] == "awaiting_retry"
        assert state["detail"] == "incorrect"

        _, state = await run_turn(capability, "s1", envelope("submit_attempt", {"answer": "2"}))
        assert state["cycle_state"] == "solved"
        assert state["detail"] == "correct"

    async def test_attempt_equivalent_form_accepted(self, capability: MathTutorCapability) -> None:
        """x=2 must count as correct for 2x+3=7 — the answer is parsed, not
        string-matched."""
        await run_turn(capability, "s2", envelope("submit_problem", {"text": "2x + 3 = 7"}))
        _, state = await run_turn(capability, "s2", envelope("submit_attempt", {"answer": "x = 2"}))
        assert state["detail"] == "correct"

    async def test_double_root_answer(self, capability: MathTutorCapability) -> None:
        await run_turn(capability, "s3", envelope("submit_problem", {"text": "x^2 - 4x + 4 = 0"}))
        _, state = await run_turn(capability, "s3", envelope("submit_attempt", {"answer": "2"}))
        assert state["detail"] == "correct"

    async def test_surd_answer_fails_closed(self, capability: MathTutorCapability) -> None:
        """√-形式作答当前不支持（parse fail-closed）；结构化 AttemptParser
        是 Phase 4 的交付。数学上正确但系统不支持的作答必须不判 CORRECT。"""
        await run_turn(capability, "s3b", envelope("submit_problem", {"text": "x^2 - 2x - 4 = 0"}))
        _, state = await run_turn(capability, "s3b", envelope("submit_attempt", {"answer": "1+\\sqrt{5}"}))
        assert state["detail"] != "correct"

    async def test_arithmetic_and_fraction_answers(self, capability: MathTutorCapability) -> None:
        await run_turn(capability, "s4", envelope("submit_problem", {"text": "3/4 + 1/2"}))
        _, state = await run_turn(capability, "s4", envelope("submit_attempt", {"answer": "5/4"}))
        assert state["detail"] == "correct"

    async def test_unparseable_attempt_asks_clarification(self, capability: MathTutorCapability) -> None:
        await run_turn(capability, "s5", envelope("submit_problem", {"text": "2x + 3 = 7"}))
        _, state = await run_turn(capability, "s5", envelope("submit_attempt", {"answer": "2 3"}))
        assert state["cycle_state"] == "awaiting_attempt_clarification"


class TestHintsAndPrompts:
    async def test_hint_returns_to_awaiting_attempt(self, capability: MathTutorCapability) -> None:
        await run_turn(capability, "s6", envelope("submit_problem", {"text": "2x + 3 = 7"}))
        contents, state = await run_turn(capability, "s6", envelope("request_hint", {}))
        # Phase 3: the message comes from the teaching chain
        # (planner → projector → writer → guard) — assert it is a real
        # non-empty tutoring utterance, not a hardcoded label.
        assert any(contents) and any(len(c) > 5 for c in contents)
        assert state["cycle_state"] == "awaiting_attempt"
        assert "submit_attempt" in state["allowed_next_inputs"]

    async def test_explanation_returns_to_awaiting_attempt(self, capability: MathTutorCapability) -> None:
        await run_turn(capability, "s7", envelope("submit_problem", {"text": "2x + 3 = 7"}))
        _, state = await run_turn(capability, "s7", envelope("request_explanation", {}))
        assert state["cycle_state"] == "awaiting_attempt"


class TestFailClosedPaths:
    async def test_attempt_worker_failure_writes_no_learning_evidence(self) -> None:
        class _AttemptCrashBackend(InProcessVerificationBackend):
            async def verify_attempt(self, student_attempt, problem, verified_candidate):
                raise VerificationWorkerCrashedError("simulated crash")

        capability = MathTutorCapability(
            service=MathTutorApplicationService(
                verification_backend=_AttemptCrashBackend()
            )
        )
        await run_turn(
            capability,
            "attempt-worker-crash",
            envelope("submit_problem", {"text": "2x + 3 = 7"}),
        )
        _, state = await run_turn(
            capability,
            "attempt-worker-crash",
            envelope("submit_attempt", {"answer": "2"}),
        )
        assert state["cycle_state"] == "awaiting_attempt_clarification"
        assert state["detail"].startswith("verification_unavailable:")
        evidence, observations = await capability.sessions.load_learning_history(
            DEV_STUDENT_ID
        )
        assert evidence == []
        assert observations == []

    async def test_ambiguous_problem(self, capability: MathTutorCapability) -> None:
        _, state = await run_turn(capability, "s8", envelope("submit_problem", {"text": "2 3"}))
        assert state["cycle_state"] == "awaiting_clarification"

    async def test_unsupported_problem(self, capability: MathTutorCapability) -> None:
        _, state = await run_turn(capability, "s9", envelope("submit_problem", {"text": "x^3 = 8"}))
        assert state["cycle_state"] == "unsupported"

    async def test_unverified_problem_blocked(self, capability: MathTutorCapability) -> None:
        # 1/0 divides by zero: parse-level unsupported; the state machine never
        # reaches AWAITING_ATTEMPT for anything unverified.
        _, state = await run_turn(capability, "s10", envelope("submit_problem", {"text": "1/0"}))
        assert state["cycle_state"] in ("unsupported", "unverified_blocked")

    async def test_cancel_closes_cycle(self, capability: MathTutorCapability) -> None:
        await run_turn(capability, "s11", envelope("submit_problem", {"text": "x^3 = 8"}))
        _, state = await run_turn(capability, "s11", envelope("cancel_turn", {}))
        assert state["cycle_state"] == "closed"


class TestSupervision:
    async def test_illegal_command_emits_error(self, capability: MathTutorCapability) -> None:
        recorder = _EventRecorder()
        recorder.start()
        context = UnifiedContext(
            session_id="s12",
            user_message=envelope("request_hint", {}),  # hints before any problem
            active_capability="math_tutor",
        )
        await capability.run(context, recorder.bus)
        await recorder.stop()
        errors = [e for e in recorder.events if e["type"] == "error"]
        assert errors, "非法命令必须返回 error 事件"

    async def test_stale_version_rejected(self, capability: MathTutorCapability) -> None:
        await run_turn(capability, "s13", envelope("submit_problem", {"text": "2x + 3 = 7"}))
        recorder = _EventRecorder()
        recorder.start()
        context = UnifiedContext(
            session_id="s13",
            user_message=envelope("submit_attempt", {"answer": "2"}, expected_version=0),  # stale: version is 3
            active_capability="math_tutor",
        )
        await capability.run(context, recorder.bus)
        await recorder.stop()
        errors = [e for e in recorder.events if e["type"] == "error"]
        assert errors and "版本" in errors[0]["content"]

    async def test_unknown_command_rejected(self, capability: MathTutorCapability) -> None:
        recorder = _EventRecorder()
        recorder.start()
        context = UnifiedContext(
            session_id="s14",
            user_message='{"command": "hack_the_planet", "payload": {}}',
            active_capability="math_tutor",
        )
        await capability.run(context, recorder.bus)
        await recorder.stop()
        errors = [e for e in recorder.events if e["type"] == "error"]
        assert errors

    async def test_plain_text_is_submit_problem(self, capability: MathTutorCapability) -> None:
        _, state = await run_turn(capability, "s15", "2x + 3 = 7")
        assert state["cycle_state"] == "awaiting_attempt"

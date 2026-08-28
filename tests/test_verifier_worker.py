"""Pre-RC verifier/CAS process-isolation acceptance tests."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
from uuid import UUID, uuid4

import pytest

from mathtutor.application.adaptive_practice import CandidateExercise
from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.practice_release import (
    ExerciseReleaseService,
    ReleaseDeniedError,
)
from mathtutor.application.verification_backend import (
    InProcessVerificationBackend,
    VerificationBackpressureError,
    VerificationResourceLimitError,
    VerificationTimeoutError,
    VerificationWorkerCrashedError,
)
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.infrastructure.verifier_worker import (
    VerificationWorkerBudget,
    VerifierWorkerManager,
    _worker_main,
    handle_request_bytes,
)
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.solving import parse_problem, solve_problem
from mathtutor.solving.strategies import _common as c

pytestmark = pytest.mark.asyncio


def _hang_worker(connection, budget) -> None:
    connection.recv_bytes()
    time.sleep(10)


def _crash_worker(connection, budget) -> None:
    connection.recv_bytes()
    os._exit(19)


def _malformed_worker(connection, budget) -> None:
    connection.recv_bytes()
    connection.send_bytes(b"{}")


def _wrong_attempt_owner_worker(connection, budget) -> None:
    raw = connection.recv_bytes()
    response, _ = handle_request_bytes(raw, budget)
    payload = json.loads(response)
    payload["assessment"]["student_id"] = str(uuid4())
    connection.send_bytes(json.dumps(payload).encode("utf-8"))


def _case(text: str = "2x + 3 = 7") -> tuple[MathProblem, MathSolutionCandidate]:
    parsed_outcome = parse_problem(text)
    assert parsed_outcome.kind == "parsed" and parsed_outcome.problem is not None
    parsed = parsed_outcome.problem
    problem = MathProblem.canonicalize(
        parsed.problem_type, parsed.normalized_ast, parsed.display_latex
    )
    solved = solve_problem(problem, parsed)
    assert solved.kind == "solved" and solved.candidate is not None
    return problem, solved.candidate


def _comparable(decision):
    return decision.model_dump(exclude={"decision_id"})


async def test_worker_matches_in_process_for_valid_and_invalid_candidates() -> None:
    in_process = InProcessVerificationBackend()
    problem, valid = _case()
    invalid = MathSolutionCandidate.canonicalize(
        problem.problem_id,
        valid.strategy,
        valid.steps,
        {"kind": "roots", "roots": (c.rational_root(99),), "latex": "x=99"},
    )
    async with VerifierWorkerManager() as worker:
        for candidate in (valid, invalid):
            expected = await in_process.verify(problem, candidate)
            actual = await worker.verify(problem, candidate)
            assert _comparable(actual) == _comparable(expected)


async def test_worker_attempt_verifier_matches_in_process() -> None:
    problem, candidate = _case()
    attempt = parse_student_attempt(
        attempt_submission_id=uuid4(),
        student_id=uuid4(),
        cycle_id=uuid4(),
        raw_text="x=2",
        attempt_index=1,
    )
    in_process = InProcessVerificationBackend()
    async with VerifierWorkerManager() as worker:
        assert await worker.verify_attempt(attempt, problem, candidate) == await in_process.verify_attempt(
            attempt, problem, candidate
        )


@pytest.mark.parametrize(
    "payload,error",
    [
        (b"not-json", "MALFORMED_REQUEST"),
        (
            json.dumps(
                {
                    "schema_version": "unknown",
                    "verification_version": "mt-verifier-v1",
                    "request_id": str(uuid4()),
                    "operation": "health",
                }
            ).encode(),
            "MALFORMED_REQUEST",
        ),
    ],
)
async def test_malformed_and_unknown_schema_rejected(payload: bytes, error: str) -> None:
    response, stop = handle_request_bytes(payload, VerificationWorkerBudget())
    assert json.loads(response)["error_code"] == error
    assert stop is False


async def test_oversized_payload_and_ast_budget_rejected() -> None:
    response, _ = handle_request_bytes(b"x" * 100, VerificationWorkerBudget(max_payload_bytes=32))
    assert json.loads(response)["error_code"] == "RESOURCE_LIMIT"

    problem, candidate = _case()
    oversized_ast = {
        "kind": "add",
        "terms": [{"kind": "num", "value": {"n": i, "d": 1}} for i in range(8)],
    }
    problem = problem.model_copy(update={"normalized_ast": oversized_ast})
    async with VerifierWorkerManager(VerificationWorkerBudget(max_ast_nodes=4)) as worker:
        with pytest.raises(VerificationResourceLimitError):
            await worker.verify(problem, candidate)


async def test_timeout_hard_kills_worker_and_fails_closed() -> None:
    worker = VerifierWorkerManager(
        VerificationWorkerBudget(wall_time_seconds=0.1), worker_target=_hang_worker
    )
    problem, candidate = _case()
    with pytest.raises(VerificationTimeoutError):
        await worker.verify(problem, candidate)
    old_pid = worker.worker_pid
    worker._worker_target = _worker_main
    worker.budget = VerificationWorkerBudget(wall_time_seconds=2.0)
    await asyncio.to_thread(worker._restart_sync)
    decision = await worker.verify(problem, candidate)
    assert decision.verdict == "VERIFIED"
    assert worker.worker_pid != old_pid
    await worker.shutdown()


async def test_worker_crash_does_not_kill_backend_and_next_request_succeeds() -> None:
    worker = VerifierWorkerManager(worker_target=_crash_worker)
    problem, candidate = _case()
    with pytest.raises(VerificationWorkerCrashedError):
        await worker.verify(problem, candidate)
    worker._worker_target = _worker_main
    await asyncio.to_thread(worker._restart_sync)
    assert (await worker.verify(problem, candidate)).verdict == "VERIFIED"
    await worker.shutdown()


async def test_malformed_response_is_fail_closed() -> None:
    worker = VerifierWorkerManager(worker_target=_malformed_worker)
    problem, candidate = _case()
    from mathtutor.application.verification_backend import VerificationMalformedResponseError

    with pytest.raises(VerificationMalformedResponseError):
        await worker.verify(problem, candidate)
    await worker.shutdown()


async def test_attempt_response_with_wrong_student_binding_is_rejected() -> None:
    from mathtutor.application.verification_backend import (
        VerificationMalformedResponseError,
    )

    problem, candidate = _case()
    attempt = parse_student_attempt(
        attempt_submission_id=uuid4(),
        student_id=uuid4(),
        cycle_id=uuid4(),
        raw_text="x=2",
        attempt_index=1,
    )
    worker = VerifierWorkerManager(worker_target=_wrong_attempt_owner_worker)
    with pytest.raises(VerificationMalformedResponseError):
        await worker.verify_attempt(attempt, problem, candidate)
    await worker.shutdown()


async def test_backpressure_is_bounded_and_fails_fast() -> None:
    worker = VerifierWorkerManager(
        VerificationWorkerBudget(wall_time_seconds=0.15, max_pending_requests=1),
        worker_target=_hang_worker,
    )
    problem, candidate = _case()
    first = asyncio.create_task(worker.verify(problem, candidate))
    await asyncio.sleep(0.02)
    started = time.monotonic()
    with pytest.raises(VerificationBackpressureError):
        await worker.verify(problem, candidate)
    assert time.monotonic() - started < 0.1
    with pytest.raises(VerificationTimeoutError):
        await first
    await worker.shutdown()


async def test_timeout_cannot_attest_and_crash_cannot_release() -> None:
    problem, _ = _case()
    timeout_worker = VerifierWorkerManager(
        VerificationWorkerBudget(wall_time_seconds=0.1), worker_target=_hang_worker
    )
    result = await MathTutorApplicationService(
        verification_backend=timeout_worker
    ).submit_problem("2x + 3 = 7")
    assert result.kind == "unverified_blocked"
    assert result.verified_ref is None and result.decision is None
    await timeout_worker.shutdown()

    crash_worker = VerifierWorkerManager(worker_target=_crash_worker)
    release_service = ExerciseReleaseService(verification_backend=crash_worker)
    exercise = CandidateExercise(
        student_id=uuid4(),
        problem_statement="2x + 3 = 7",
        skill_ids=("linear_equation.solve",),
        concept_ids=("linear_equations",),
        difficulty=2,
        generated_by="test",
    )
    with pytest.raises(ReleaseDeniedError):
        await release_service.release_candidate(exercise)
    await crash_worker.shutdown()


async def test_hash_version_binding_shutdown_and_restart_safety() -> None:
    problem, candidate = _case("x^2 - 5x + 6 = 0")
    first = VerifierWorkerManager()
    await first.start()
    decision = await first.verify(problem, candidate)
    assert decision.problem_content_hash == problem.content_hash
    assert decision.candidate_payload_hash == candidate.payload_hash
    assert decision.policy_version == "v1"
    started = time.monotonic()
    await first.shutdown()
    assert time.monotonic() - started < 2.0
    assert first.worker_pid is None

    async with VerifierWorkerManager() as restarted:
        assert (await restarted.verify(problem, candidate)).verdict == "VERIFIED"


async def test_worker_contract_has_no_path_network_or_model_dependency() -> None:
    import inspect
    import mathtutor.infrastructure.verifier_worker as module

    request_fields = set(module._RequestEnvelope.model_fields)
    assert not ({"path", "url", "api_key", "student_state", "raw_prompt"} & request_fields)
    source = inspect.getsource(module._worker_main)
    assert "GenerativeModelGateway" not in source
    assert "import http" not in source.lower()
    assert module.VerifierWorkerManager.capabilities.network_dependency == "UNAVAILABLE"
    assert module.VerifierWorkerManager.capabilities.user_filesystem_input == "UNAVAILABLE"

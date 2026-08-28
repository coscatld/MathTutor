"""Single managed verifier worker with a typed, JSON-only IPC boundary.

Only UTF-8 JSON bytes cross ``send_bytes``/``recv_bytes``.  The request is
constructed from server-owned domain objects; no client-supplied JSON is
ever deserialized with pickle.  The child imports and calls the existing
``solving.verifier.verify`` function, so process isolation creates no second
mathematical authority.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
import threading
import time
from typing import Any, Callable, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mathtutor.application.verification_backend import (
    AUTHORITATIVE_VERIFIER_VERSION,
    VERIFICATION_SCHEMA_VERSION,
    VerificationBackpressureError,
    VerificationMalformedResponseError,
    VerificationResourceLimitError,
    VerificationTimeoutError,
    VerificationWorkerCrashedError,
)
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.attempt import StudentAttempt
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerificationDecision,
)
from mathtutor.solving import nodes as n
from mathtutor.learning.attempt_verifier import AttemptAssessment


class _RequestEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[VERIFICATION_SCHEMA_VERSION]
    verification_version: Literal[AUTHORITATIVE_VERIFIER_VERSION]
    request_id: UUID
    operation: Literal["verify", "verify_attempt", "health", "shutdown"]
    problem: dict[str, Any] | None = None
    candidate: dict[str, Any] | None = None
    student_attempt: dict[str, Any] | None = None


class _ResponseEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[VERIFICATION_SCHEMA_VERSION]
    verification_version: Literal[AUTHORITATIVE_VERIFIER_VERSION]
    request_id: UUID
    status: Literal["ok", "error"]
    decision: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class VerificationWorkerBudget:
    wall_time_seconds: float = 2.0
    max_payload_bytes: int = 256 * 1024
    max_ast_nodes: int = 512
    max_polynomial_degree: int = 64
    max_steps: int = 512
    max_pending_requests: int = 4
    shutdown_timeout_seconds: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "wall_time_seconds",
            "max_payload_bytes",
            "max_ast_nodes",
            "max_polynomial_degree",
            "max_steps",
            "max_pending_requests",
            "shutdown_timeout_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class WorkerIsolationCapabilities:
    wall_clock_hard_kill: Literal["SUPPORTED"] = "SUPPORTED"
    payload_ast_step_budget: Literal["SUPPORTED"] = "SUPPORTED"
    network_dependency: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    user_filesystem_input: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    memory_limit: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    cpu_time_limit: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    network_access_control: Literal["UNAVAILABLE"] = "UNAVAILABLE"


def _json_bytes(value: BaseModel) -> bytes:
    return value.model_dump_json(exclude_none=True).encode("utf-8")


def _response(
    request_id: UUID,
    *,
    decision: VerificationDecision | None = None,
    assessment: AttemptAssessment | None = None,
    error_code: str = "",
    error_message: str = "",
) -> bytes:
    return _json_bytes(
        _ResponseEnvelope(
            schema_version=VERIFICATION_SCHEMA_VERSION,
            verification_version=AUTHORITATIVE_VERIFIER_VERSION,
            request_id=request_id,
            status="ok" if not error_code else "error",
            decision=decision.model_dump(mode="json") if decision else None,
            assessment=assessment.model_dump(mode="json") if assessment else None,
            error_code=error_code,
            error_message=error_message,
        )
    )


def _ast_budget(ast: Any) -> tuple[int, int]:
    """Return (node count, largest explicit exponent) without recursion."""
    count = 0
    max_degree = 0
    pending = [ast]
    while pending:
        current = pending.pop()
        if not isinstance(current, dict):
            raise ValueError("AST node must be an object")
        count += 1
        kind = current.get("kind")
        if kind == "pow":
            exp = current.get("exp")
            if not isinstance(exp, int):
                raise ValueError("AST exponent must be an integer")
            max_degree = max(max_degree, exp)
            pending.append(current.get("base"))
        elif kind in {"add", "mul"}:
            key = "terms" if kind == "add" else "factors"
            children = current.get(key)
            if not isinstance(children, list):
                raise ValueError(f"AST {key} must be an array")
            pending.extend(children)
        elif kind == "div":
            pending.extend((current.get("num"), current.get("den")))
        elif kind == "equation":
            pending.extend((current.get("lhs"), current.get("rhs")))
        elif kind in {"num", "var"}:
            pass
        else:
            raise ValueError(f"unknown AST kind: {kind!r}")
    return count, max_degree


def _validate_work(request: _RequestEnvelope, budget: VerificationWorkerBudget) -> tuple[MathProblem, MathSolutionCandidate]:
    if request.operation not in {"verify", "verify_attempt"} or request.problem is None or request.candidate is None:
        raise ValueError("verification requires problem and candidate")
    if len(request.candidate.get("steps") or ()) > budget.max_steps:
        raise VerificationResourceLimitError("candidate step budget exceeded")
    count, degree = _ast_budget(request.problem.get("normalized_ast"))
    if count > budget.max_ast_nodes:
        raise VerificationResourceLimitError("AST node budget exceeded")
    if degree > budget.max_polynomial_degree:
        raise VerificationResourceLimitError("polynomial degree budget exceeded")
    problem = MathProblem.model_validate(request.problem)
    candidate = MathSolutionCandidate.model_validate(request.candidate)
    # JSON has one array type while the frozen domain contract uses tuples
    # for root sets. Restore those declared shapes before calling the same
    # verifier; this is transport decoding, not mathematical interpretation.
    final_answer = dict(candidate.final_answer)
    if isinstance(final_answer.get("roots"), list):
        final_answer["roots"] = tuple(final_answer["roots"])
    restored_steps: list[dict[str, Any]] = []
    for raw_step in candidate.steps:
        step = dict(raw_step)
        if isinstance(step.get("roots"), list):
            step["roots"] = tuple(step["roots"])
        restored_steps.append(step)
    candidate = candidate.model_copy(
        update={"final_answer": final_answer, "steps": tuple(restored_steps)}
    )
    # Contract validation only: malformed canonical ASTs are IPC failures;
    # mathematical acceptance remains exclusively in verifier.py.
    ast = n.from_dict(problem.normalized_ast)
    if n.to_dict(ast) != problem.normalized_ast:
        raise ValueError("AST is not canonical")
    return problem, candidate


def handle_request_bytes(raw: bytes, budget: VerificationWorkerBudget) -> tuple[bytes, bool]:
    """Validate and execute one IPC message; exposed for contract tests."""
    fallback_id = UUID(int=0)
    try:
        if len(raw) > budget.max_payload_bytes:
            return _response(fallback_id, error_code="RESOURCE_LIMIT", error_message="payload too large"), False
        decoded = json.loads(raw.decode("utf-8"))
        request = _RequestEnvelope.model_validate(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError) as exc:
        return _response(fallback_id, error_code="MALFORMED_REQUEST", error_message=str(exc)), False

    if request.operation == "health":
        return _response(request.request_id), False
    if request.operation == "shutdown":
        return _response(request.request_id), True
    try:
        problem, candidate = _validate_work(request, budget)
        if request.operation == "verify_attempt":
            if request.student_attempt is None:
                raise ValueError("verify_attempt requires student_attempt")
            student_attempt = StudentAttempt.model_validate(request.student_attempt)
            if len(student_attempt.parsed_steps) > budget.max_steps:
                raise VerificationResourceLimitError("attempt step budget exceeded")
            from mathtutor.learning.attempt_verifier import verify_attempt

            return _response(
                request.request_id,
                assessment=verify_attempt(student_attempt, problem, candidate),
            ), False
        # Imported here to keep the authority visually explicit at the child
        # execution boundary and easy to monkeypatch in process-level tests.
        from mathtutor.solving.verifier import verify

        return _response(request.request_id, decision=verify(problem, candidate)), False
    except VerificationResourceLimitError as exc:
        return _response(request.request_id, error_code="RESOURCE_LIMIT", error_message=str(exc)), False
    except (ValidationError, ValueError, TypeError, KeyError, n.MathDomainError) as exc:
        return _response(request.request_id, error_code="MALFORMED_REQUEST", error_message=str(exc)), False
    except BaseException as exc:  # child contains unexpected verifier failures
        return _response(request.request_id, error_code="VERIFIER_ERROR", error_message=type(exc).__name__), False


def _worker_main(connection: Connection, budget: VerificationWorkerBudget) -> None:
    # No gateway, credential, URL, document path, or HTTP client is passed to
    # this target. Remove inherited secrets after spawn; Python already has
    # its import paths at this point.
    os.environ.clear()
    try:
        while True:
            raw = connection.recv_bytes(budget.max_payload_bytes + 1)
            response, stop = handle_request_bytes(raw, budget)
            connection.send_bytes(response)
            if stop:
                return
    except (EOFError, OSError):
        return
    finally:
        connection.close()


class VerifierWorkerManager:
    """One managed child, fail-fast bounded backlog, hard timeout restart."""

    capabilities = WorkerIsolationCapabilities()

    def __init__(
        self,
        budget: VerificationWorkerBudget | None = None,
        *,
        mp_context: str = "spawn",
        worker_target: Callable[[Connection, VerificationWorkerBudget], None] = _worker_main,
    ) -> None:
        self.budget = budget or VerificationWorkerBudget()
        self._ctx = multiprocessing.get_context(mp_context)
        self._worker_target = worker_target
        self._process: multiprocessing.Process | None = None
        self._connection: Connection | None = None
        self._state_lock = threading.RLock()
        self._request_lock = asyncio.Lock()
        self._pending_lock = asyncio.Lock()
        self._pending = 0
        self._accepting = True

    @property
    def worker_pid(self) -> int | None:
        process = self._process
        return process.pid if process and process.is_alive() else None

    async def start(self) -> None:
        self._accepting = True
        await asyncio.to_thread(self._ensure_started_sync)
        await self.health()

    def _ensure_started_sync(self) -> None:
        with self._state_lock:
            if self._process is not None and self._process.is_alive() and self._connection is not None:
                return
            self._dispose_sync()
            parent, child = self._ctx.Pipe(duplex=True)
            process = self._ctx.Process(
                target=self._worker_target,
                args=(child, self.budget),
                name="mathtutor-verifier-worker",
                daemon=True,
            )
            process.start()
            child.close()
            self._process = process
            self._connection = parent

    async def health(self) -> bool:
        async with self._request_lock:
            request_id = uuid4()
            response = await asyncio.to_thread(
                self._round_trip_sync,
                _RequestEnvelope(
                    schema_version=VERIFICATION_SCHEMA_VERSION,
                    verification_version=AUTHORITATIVE_VERIFIER_VERSION,
                    request_id=request_id,
                    operation="health",
                ),
            )
            return response.status == "ok" and response.request_id == request_id

    async def restart(self) -> None:
        """Hard-replace the child and require a fresh health response."""
        if not self._accepting:
            raise VerificationWorkerCrashedError("verifier worker is shutting down")
        async with self._request_lock:
            await asyncio.to_thread(self._restart_sync)
            if not await asyncio.to_thread(self._probe_health_sync):
                raise VerificationWorkerCrashedError("verifier worker restart failed")

    async def verify(self, problem: MathProblem, candidate: MathSolutionCandidate) -> VerificationDecision:
        async with self._pending_lock:
            if not self._accepting:
                raise VerificationWorkerCrashedError("verifier worker is shutting down")
            if self._pending >= self.budget.max_pending_requests:
                raise VerificationBackpressureError("verifier backlog is full")
            self._pending += 1
        try:
            async with self._request_lock:
                request_id = uuid4()
                request = _RequestEnvelope(
                    schema_version=VERIFICATION_SCHEMA_VERSION,
                    verification_version=AUTHORITATIVE_VERIFIER_VERSION,
                    request_id=request_id,
                    operation="verify",
                    problem=problem.model_dump(mode="json"),
                    candidate=candidate.model_dump(mode="json"),
                )
                raw = _json_bytes(request)
                if len(raw) > self.budget.max_payload_bytes:
                    raise VerificationResourceLimitError("payload byte budget exceeded")
                response = await asyncio.to_thread(self._round_trip_sync, request)
                if response.request_id != request_id:
                    await asyncio.to_thread(self._restart_sync)
                    raise VerificationMalformedResponseError("response request_id mismatch")
                if response.status != "ok" or response.decision is None:
                    if response.error_code == "RESOURCE_LIMIT":
                        raise VerificationResourceLimitError(response.error_message)
                    raise VerificationMalformedResponseError(
                        f"worker rejected request: {response.error_code}"
                    )
                try:
                    decision = VerificationDecision.model_validate(response.decision)
                except ValidationError as exc:
                    await asyncio.to_thread(self._restart_sync)
                    raise VerificationMalformedResponseError("invalid decision schema") from exc
                if (
                    decision.problem_id != problem.problem_id
                    or decision.problem_content_hash != problem.content_hash
                    or decision.candidate_id != candidate.candidate_id
                    or decision.candidate_payload_hash != candidate.payload_hash
                ):
                    await asyncio.to_thread(self._restart_sync)
                    raise VerificationMalformedResponseError("decision binding mismatch")
                return decision
        finally:
            async with self._pending_lock:
                self._pending -= 1

    async def verify_attempt(
        self,
        student_attempt: StudentAttempt,
        problem: MathProblem,
        verified_candidate: MathSolutionCandidate,
    ) -> AttemptAssessment:
        async with self._pending_lock:
            if not self._accepting:
                raise VerificationWorkerCrashedError("verifier worker is shutting down")
            if self._pending >= self.budget.max_pending_requests:
                raise VerificationBackpressureError("verifier backlog is full")
            self._pending += 1
        try:
            async with self._request_lock:
                request_id = uuid4()
                request = _RequestEnvelope(
                    schema_version=VERIFICATION_SCHEMA_VERSION,
                    verification_version=AUTHORITATIVE_VERIFIER_VERSION,
                    request_id=request_id,
                    operation="verify_attempt",
                    problem=problem.model_dump(mode="json"),
                    candidate=verified_candidate.model_dump(mode="json"),
                    student_attempt=student_attempt.model_dump(mode="json"),
                )
                response = await asyncio.to_thread(self._round_trip_sync, request)
                if response.request_id != request_id or response.status != "ok" or response.assessment is None:
                    await asyncio.to_thread(self._restart_sync)
                    if response.error_code == "RESOURCE_LIMIT":
                        raise VerificationResourceLimitError(response.error_message)
                    raise VerificationMalformedResponseError("worker rejected attempt request")
                try:
                    assessment = AttemptAssessment.model_validate(response.assessment)
                except ValidationError as exc:
                    await asyncio.to_thread(self._restart_sync)
                    raise VerificationMalformedResponseError("invalid assessment schema") from exc
                if (
                    assessment.attempt_id != student_attempt.attempt_id
                    or assessment.student_id != student_attempt.student_id
                    or assessment.problem_id != problem.problem_id
                    or assessment.reference_solution_payload_hash != verified_candidate.payload_hash
                ):
                    await asyncio.to_thread(self._restart_sync)
                    raise VerificationMalformedResponseError("assessment binding mismatch")
                return assessment
        finally:
            async with self._pending_lock:
                self._pending -= 1

    def _round_trip_sync(self, request: _RequestEnvelope) -> _ResponseEnvelope:
        self._ensure_started_sync()
        raw = _json_bytes(request)
        if len(raw) > self.budget.max_payload_bytes:
            raise VerificationResourceLimitError("payload byte budget exceeded")
        with self._state_lock:
            connection = self._connection
            process = self._process
            assert connection is not None and process is not None
            try:
                connection.send_bytes(raw)
                if not connection.poll(self.budget.wall_time_seconds):
                    self._restart_sync()
                    raise VerificationTimeoutError("verifier wall-clock deadline exceeded")
                response_raw = connection.recv_bytes(self.budget.max_payload_bytes + 1)
            except VerificationTimeoutError:
                raise
            except (EOFError, OSError, BrokenPipeError) as exc:
                self._restart_sync()
                raise VerificationWorkerCrashedError("verifier worker crashed") from exc
        try:
            if len(response_raw) > self.budget.max_payload_bytes:
                raise ValueError("response too large")
            return _ResponseEnvelope.model_validate_json(response_raw)
        except (ValidationError, ValueError) as exc:
            self._restart_sync()
            raise VerificationMalformedResponseError("malformed worker response") from exc

    def _restart_sync(self) -> None:
        with self._state_lock:
            self._dispose_sync()
            if self._accepting:
                self._ensure_started_sync()
                if not self._probe_health_sync():
                    self._dispose_sync()

    def _probe_health_sync(self) -> bool:
        """Functional post-restart health check without recursive restart."""
        connection, process = self._connection, self._process
        if connection is None or process is None or not process.is_alive():
            return False
        request_id = uuid4()
        request = _RequestEnvelope(
            schema_version=VERIFICATION_SCHEMA_VERSION,
            verification_version=AUTHORITATIVE_VERIFIER_VERSION,
            request_id=request_id,
            operation="health",
        )
        try:
            connection.send_bytes(_json_bytes(request))
            if not connection.poll(self.budget.wall_time_seconds):
                return False
            response = _ResponseEnvelope.model_validate_json(
                connection.recv_bytes(self.budget.max_payload_bytes + 1)
            )
        except (EOFError, OSError, ValidationError, ValueError):
            return False
        return response.status == "ok" and response.request_id == request_id

    def _dispose_sync(self) -> None:
        connection, process = self._connection, self._process
        self._connection = None
        self._process = None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        if process is not None:
            if process.is_alive():
                process.terminate()
                process.join(self.budget.shutdown_timeout_seconds)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(self.budget.shutdown_timeout_seconds)
            if not process.is_alive():
                process.join(timeout=0)

    async def shutdown(self) -> None:
        self._accepting = False
        # The request lock provides a bounded drain. If an active request is
        # stuck its own wall deadline kills the child before this wait ends.
        try:
            await asyncio.wait_for(
                self._request_lock.acquire(),
                timeout=self.budget.wall_time_seconds + self.budget.shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError:
            await asyncio.to_thread(self._dispose_sync)
            return
        try:
            await asyncio.to_thread(self._dispose_sync)
        finally:
            self._request_lock.release()

    async def __aenter__(self) -> "VerifierWorkerManager":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.shutdown()


__all__ = [
    "VerificationWorkerBudget",
    "VerifierWorkerManager",
    "WorkerIsolationCapabilities",
    "handle_request_bytes",
]

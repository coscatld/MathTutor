"""Application service: fail-closed submit_problem and attestation commit."""

from __future__ import annotations

import pytest

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.repositories.solution_repository import (
    AttestationDeniedError,
    InMemorySolutionRepository,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def service() -> MathTutorApplicationService:
    return MathTutorApplicationService()


class TestSubmitProblem:
    async def test_verified_path(self, service: MathTutorApplicationService) -> None:
        result = await service.submit_problem("2x + 3 = 7")
        assert result.kind == "verified"
        assert result.problem is not None
        assert result.problem.problem_type == "linear"
        assert result.verified_ref is not None
        assert result.decision is not None and result.decision.verdict == "VERIFIED"
        assert result.verified_ref.problem_content_hash == result.problem.content_hash
        assert result.verified_ref.solution_candidate_id == result.candidate.candidate_id

    async def test_unsupported_fail_closed(self, service: MathTutorApplicationService) -> None:
        for text in ("x^3 = 8", "1/0", "\\sqrt{4} + 1", "1/x = 2"):
            result = await service.submit_problem(text)
            assert result.kind == "unsupported", text
            assert result.verified_ref is None
            assert result.decision is None

    async def test_ambiguous_fail_closed(self, service: MathTutorApplicationService) -> None:
        result = await service.submit_problem("2 3")
        assert result.kind == "ambiguous"
        assert result.verified_ref is None

    async def test_quadratic_verified(self, service: MathTutorApplicationService) -> None:
        result = await service.submit_problem("x^2 - 5x + 6 = 0")
        assert result.kind == "verified"
        assert result.problem is not None and result.problem.problem_type == "quadratic"

    async def test_deterministic_and_deduped(self, service: MathTutorApplicationService) -> None:
        first = await service.submit_problem("x^2 = 5")
        second = await service.submit_problem("x^2 = 5")
        # Canonical problems dedupe by content hash; each turn gets its own
        # verification log and attestation.
        assert first.problem.problem_id == second.problem.problem_id
        assert first.problem.content_hash == second.problem.content_hash
        assert first.verified_ref.verification_log_id != second.verified_ref.verification_log_id
        assert first.verified_ref.problem_content_hash == second.verified_ref.problem_content_hash
        assert first.verified_ref.attestation_hash != second.verified_ref.attestation_hash

    async def test_distinct_problems_distinct_ids(self, service: MathTutorApplicationService) -> None:
        a = await service.submit_problem("x^2 = 5")
        b = await service.submit_problem("x^2 = 2")
        assert a.problem.problem_id != b.problem.problem_id


class TestAttestationFailClosed:
    async def test_repository_refuses_unverified(self) -> None:
        from mathtutor.domain.solution import VerificationCheck

        repo = InMemorySolutionRepository()
        service = MathTutorApplicationService(solutions=repo)
        result = await service.submit_problem("2x + 3 = 7")
        assert result.kind == "verified"

        # A decision with a failed check must be refused even if its verdict
        # was forged to VERIFIED.
        forged = result.decision.model_copy(
            update={
                "verdict": "VERIFIED",
                "checks": (VerificationCheck(name="domain", status="failed", detail="forged"),),
            }
        )
        with pytest.raises(AttestationDeniedError):
            await repo.issue_attestation(result.problem, result.candidate, forged)

    async def test_repository_refuses_unbound_hash(self, service: MathTutorApplicationService) -> None:
        result = await service.submit_problem("2x + 3 = 7")
        assert result.kind == "verified"
        assert result.decision is not None and result.problem is not None and result.candidate is not None
        forged = result.decision.model_copy(update={"problem_content_hash": "deadbeef"})
        with pytest.raises(AttestationDeniedError):
            await service.solutions.issue_attestation(result.problem, result.candidate, forged)

    async def test_attestation_immutable_and_queryable(self, service: MathTutorApplicationService) -> None:
        result = await service.submit_problem("x^2 - 5x + 6 = 0")
        assert result.kind == "verified"
        ref = result.verified_ref
        assert ref is not None
        assert await service.solutions.get_attestation(ref.verification_log_id) == ref
        assert await service.solutions.get_attestation_for_problem(result.problem.problem_id) == ref

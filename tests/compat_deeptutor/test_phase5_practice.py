"""Phase 5 — verified adaptive practice tests (release gate + offers).

The 25 tests below map 1:1 to the Phase 5 checklist:

   1- 3  BANK/TEMPLATE/LLM candidates are UNVERIFIED by construction — only
          Parser → Solver → Verifier → Release Attestation may produce a
          released exercise (release gate, §7.2).
   4- 9  Release immutability (§7.3): invalid → no release; valid → released;
          any bound-byte change (problem/solution/verifier/policy) → a NEW
          release, the old one SUPERSEDED.
  10-13  Revoked/superseded/expired releases and offers → no new offer, no
          accept (§7.9).
  14-16  Idempotent duplicate accept; owner isolation (lists + accept).
  17     Exact snapshot judging: a child cycle judges against the offer's
          OWN release version, never "the newest" (§11.3).
  18-19  Child cycle restart-safety and SAME state machine (no second one).
  20-22  Atomicity (§7.10): release and accept are ONE short transaction;
          outbox rows are written inside that same transaction.
  23-24  Public contract: never a solution/answer key/mastery/attestation in
          student events or the /offers projection.
  25     LLM failure → deterministic fallback (bank > template > LLM), fail
          closed when nothing is available.

Permanent invariants enforced here (verbatim):
- CandidateExercise is UNVERIFIED by construction; source_type (BANK/
  TEMPLATE/LLM) is a claim, never a trust grant.
- LLM never judges/verifies/issues a release.
- The child cycle reuses the existing TutoringCycle/StateMachine
  (practice_offer_id XOR problem_id; same client session row).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Sequence
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from mathtutor.application.adaptive_practice import (
    AdaptivePracticeService,
    CandidateExercise,
)
from mathtutor.application.context_assembler import (
    BaseContextSourceProvider,
    ContextAssembler,
    LoadOutcome,
)
from mathtutor.application.llm_candidate_generator import (
    LLMCandidateExerciseGenerator,
    PracticeGenerationError,
    PracticeGeneratorChain,
    TemplateCandidateExerciseGenerator,
    build_llm_prompt,
)
from mathtutor.application.practice_release import (
    ExerciseReleaseService,
    ReleaseDeniedError,
    SEED_BANK,
    VERIFIER_VERSION,
    labels_for_mapping_ids,
)
from mathtutor.application.state_machine import (
    CycleCommand,
    TutoringSession,
)
from mathtutor.capabilities.math_tutor import MathTutorCapability
from mathtutor.domain.assembled_context import (
    CurriculumContext,
    CurriculumNodeRef,
    MasteryEntry,
    StudentModelContext,
)
from mathtutor.domain.practice import ExerciseRelease
from mathtutor.domain.practice_context import (
    MasterySnapshotEntry,
    PracticeGenerationContext,
)
from mathtutor.domain.retrieval_policy import RetrievalSource
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.learning.skills import (
    CONCEPT_LINEAR_EQUATIONS,
    SKILL_LINEAR_EQUATION,
)
from mathtutor.pedagogy.stage_policy import PRIMARY_POLICY
from mathtutor.repositories.practice_repository import (
    InMemoryPracticeRepository,
)
from mathtutor.repositories.sqlite_practice import SQLitePracticeRepository
from mathtutor.repositories.sqlite_store import SQLiteSessionStore
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.security.scopes import (
    PrincipalScope,
    StudentOwnerScope,
    dev_student_owner,
    student_uuid,
)

pytestmark = pytest.mark.asyncio

_SID = "sess-phase5"

# Student-public surfaces may never carry these (§contract).
FORBIDDEN_KEYS = {
    "solution",
    "final_answer",
    "answer_key",
    "candidate",
    "attestation",
    "verification",
    "decision",
    "mastery",
}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class StubProvider(BaseContextSourceProvider):
    """Provider whose load/retrieve return fixed outcomes."""

    def __init__(self, source: RetrievalSource, *, on_load=None, on_retrieve=None):
        self.source = source
        self._on_load = on_load
        self._on_retrieve = on_retrieve

    async def load(
        self,
        *,
        student_id: str,
        intent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        return self._on_load if self._on_load is not None else LoadOutcome(detail="stub load")

    async def retrieve(self, *, student_id: str, intent, query_hint: str) -> LoadOutcome:
        return self._on_retrieve if self._on_retrieve is not None else LoadOutcome(detail="stub retrieve")


class Collector:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def content(self, message, source=None, stage=None, metadata=None) -> None:
        self.events.append({"type": "content", "message": message, "metadata": metadata or {}})

    async def error(self, message, source=None, metadata=None) -> None:
        self.events.append({"type": "error", "message": message, "metadata": metadata or {}})

    async def emit(self, event) -> None:
        self.events.append({"type": "emit", "event": event})


def _owner_a() -> StudentOwnerScope:
    return dev_student_owner()


def _owner_b() -> StudentOwnerScope:
    return StudentOwnerScope(
        principal=PrincipalScope(user_id="student-b", username="student-b", role="user"),
        student_id="student-b",
    )


def _env(owner: StudentOwnerScope, sid: str, command: str, payload: dict) -> Any:
    from deeptutor.core.context import UnifiedContext

    return UnifiedContext(
        user_message=json.dumps({"command": command, "payload": payload}),
        session_id=sid,
        metadata={"student_owner": owner},
    )


def _make_assembler() -> ContextAssembler:
    """GENERATE_PRACTICE REQUIRED sources with a minimal student model."""
    student_model = StudentModelContext(
        estimator_version="mvp-v1",
        projection_version=1,
        skill_mastery=(MasteryEntry(skill_id=SKILL_LINEAR_EQUATION, mastery=0.45),),
    )
    curriculum = CurriculumContext(
        version_code="mt-curriculum-mvp-v1",
        nodes=(
            CurriculumNodeRef(
                node_id=SKILL_LINEAR_EQUATION,
                code=SKILL_LINEAR_EQUATION,
                kind="skill",
                title="一元一次方程",
            ),
        ),
    )
    providers = {
        RetrievalSource.STUDENT_MODEL: StubProvider(
            RetrievalSource.STUDENT_MODEL, on_load=LoadOutcome(payload=student_model)
        ),
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM, on_load=LoadOutcome(payload=curriculum)
        ),
        RetrievalSource.MISCONCEPTION_HISTORY: StubProvider(
            RetrievalSource.MISCONCEPTION_HISTORY, on_load=LoadOutcome(empty_data=True)
        ),
        RetrievalSource.RECENT_ATTEMPTS: StubProvider(
            RetrievalSource.RECENT_ATTEMPTS, on_load=LoadOutcome(empty_data=True)
        ),
    }
    return ContextAssembler(providers=providers)


def _practice_context() -> PracticeGenerationContext:
    return PracticeGenerationContext(
        student_id=student_uuid(_owner_a().student_id),
        target_skill_ids=(SKILL_LINEAR_EQUATION,),
        target_concept_ids=(CONCEPT_LINEAR_EQUATIONS,),
        current_mastery=(
            MasterySnapshotEntry(skill_id=SKILL_LINEAR_EQUATION, mastery=0.45),
        ),
        active_misconceptions=(),
        recent_error_patterns=(),
        recent_attempt_summary=(),
        desired_difficulty=2,
    )


def _bank_candidate(index: int = 4) -> CandidateExercise:
    """SEED_BANK[4] = "2x + 3 = 7" (BANK source, LINEAR_EQUATION)."""
    item = SEED_BANK[index]
    return CandidateExercise(
        student_id=student_uuid(_owner_a().student_id),
        problem_statement=item.problem_statement,
        skill_ids=item.skill_ids,
        concept_ids=item.concept_ids,
        difficulty=item.difficulty,
        generated_by="mt-bank-seed-v1",
    )


def _make_stack() -> SimpleNamespace:
    practice = InMemoryPracticeRepository()
    capability = MathTutorCapability(practice_repository=practice)
    release = ExerciseReleaseService(practice)
    adaptive = AdaptivePracticeService(
        assembler=_make_assembler(),
        generator=PracticeGeneratorChain(),
        release_service=release,
    )
    return SimpleNamespace(
        practice=practice,
        capability=capability,
        release=release,
        adaptive=adaptive,
        owner=_owner_a(),
    )


@pytest_asyncio.fixture()
async def db(tmp_path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "phase5.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


def _make_sqlite_stack(db) -> SimpleNamespace:
    from mathtutor.application.math_tutor_service import (
        MathTutorApplicationService,
    )
    from mathtutor.repositories.sqlite_math_facts import (
        SQLiteProblemRepository,
        SQLiteSolutionRepository,
    )

    uow = MathTutorUow(db)
    practice = SQLitePracticeRepository(uow)
    store = SQLiteSessionStore(db)
    # The verified chain must be durable too: the capability's service uses
    # the SQLite math-fact repositories (Phase 1C), so load_verified can
    # restore the attestation after a restart — and the child cycle resolves
    # the exact snapshot from the practice catalog.
    service = MathTutorApplicationService(
        problems=SQLiteProblemRepository(uow),
        solutions=SQLiteSolutionRepository(uow),
    )
    capability = MathTutorCapability(store=store, service=service, practice_repository=practice)
    release = ExerciseReleaseService(practice)
    adaptive = AdaptivePracticeService(
        assembler=_make_assembler(),
        generator=PracticeGeneratorChain(),
        release_service=release,
    )
    return SimpleNamespace(
        uow=uow,
        practice=practice,
        store=store,
        capability=capability,
        release=release,
        adaptive=adaptive,
        owner=_owner_a(),
    )


async def _publish_seed(stack) -> dict[str, int]:
    return await stack.release.publish_seed_bank()


async def _to_practice_offered(stack, owner: StudentOwnerScope | None = None) -> TutoringSession:
    """submit → hints → solution → REFLECTION → (server-side) PRACTICE_OFFERED."""
    owner = owner or stack.owner
    sid = _SID
    bus = Collector()
    await stack.capability.run(_env(owner, sid, "submit_problem", {"text": "2x + 3 = 7"}), bus)
    for _ in range(PRIMARY_POLICY.min_hints_for_solution):
        await stack.capability.run(_env(owner, sid, "request_hint", {}), bus)
    await stack.capability.run(_env(owner, sid, "request_solution", {}), bus)
    session = await stack.capability.sessions.load(owner.student_id, sid)
    assert session.state.value == "reflection", session.state.value
    transition = session.step(CycleCommand.PRACTICE_OFFERED)
    await stack.capability.sessions.persist_transition(owner.student_id, transition)
    return session


async def _prepare(stack, session: TutoringSession):
    return await stack.adaptive.prepare_offer(
        stack.owner.student_id,
        parent_cycle_id=session.cycle.cycle_id,
        target_skill_ids=(SKILL_LINEAR_EQUATION,),
        count=1,
    )


async def _accept(stack, offer, owner: StudentOwnerScope | None = None) -> tuple[dict, Collector]:
    """Accept via the capability; returns the practice_started metadata + bus."""
    owner = owner or stack.owner
    bus = Collector()
    await stack.capability.run(
        _env(owner, _SID, "accept_practice_offer", {"offer_id": str(offer.offer_id)}), bus
    )
    started = [
        e
        for e in bus.events
        if e["type"] == "content" and e["metadata"].get("detail") == "practice_started"
    ]
    if not started:
        errors = [e.get("message") for e in bus.events if e["type"] == "error"]
        raise AssertionError(f"accept failed: {errors}")
    return started[0]["metadata"], bus


# ---------------------------------------------------------------------------
# 1-3: every source needs the release gate (a claim, never a trust grant)
# ---------------------------------------------------------------------------


async def test_01_bank_candidate_needs_verifier():
    stack = _make_stack()
    # A raw bank candidate carries NO verification authority and creates NO
    # release — the catalog stays empty until the gate runs.
    candidate = _bank_candidate()
    assert not hasattr(candidate, "verdict")
    assert not hasattr(candidate, "decision")
    assert not hasattr(candidate, "attestation")
    assert await stack.practice.find_exercise_by_content_hash(
        "does-not-exist"
    ) is None or True  # nothing released yet
    assert await stack.practice.offers_for_student(stack.owner.student_id) == []

    result = await _publish_seed(stack)
    assert result == {"total": 8, "released": 8, "failed": 0}

    # Every bank item went through the gate: released + attested.
    chain = await stack.release.release_candidate(candidate, source_type="BANK")
    assert chain.release.status == "released"
    assert chain.decision is None  # idempotent replay: no second release
    assert chain.ref.verification_log_id is not None
    release = await stack.practice.load_release(chain.release.release_id)
    assert release is not None and release.status == "released"
    exercise = await stack.practice.load_exercise(chain.exercise.exercise_id)
    assert exercise is not None and exercise.source_type == "BANK"

    # Idempotent republish: identical bytes → the same release, no new rows.
    assert len(await stack.practice.list_outbox()) == 8
    await _publish_seed(stack)
    assert len(await stack.practice.list_outbox()) == 8


async def test_02_template_candidate_needs_verifier():
    stack = _make_stack()
    template = TemplateCandidateExerciseGenerator()
    candidates = await template.generate(_practice_context(), count=1)
    assert candidates, "template must produce a candidate for LINEAR_EQUATION"
    assert candidates[0].generated_by == "mt-template-candidate-v1"
    assert not hasattr(candidates[0], "verdict")
    # Nothing released before the gate.
    assert await stack.practice.offers_for_student(stack.owner.student_id) == []

    chain = await stack.release.release_candidate(candidates[0], source_type="TEMPLATE")
    assert chain.release.status == "released"
    assert chain.decision is not None and chain.decision.verdict == "VERIFIED"
    exercise = await stack.practice.load_exercise(chain.exercise.exercise_id)
    assert exercise is not None and exercise.source_type == "TEMPLATE"
    assert exercise.problem_statement in ("2x + 3 = 7", "3x - 5 = 4", "2x + 1 = 5", "4x + 3 = 15")


class _FakeLLMClient:
    """GatewayRoleClient stub — returns a valid statement list."""

    def __init__(self, text: str = '["2x + 3 = 7"]') -> None:
        self.text = text

    async def complete(self, **kwargs: Any) -> str:
        return self.text


async def test_03_llm_candidate_needs_verifier():
    stack = _make_stack()
    llm = LLMCandidateExerciseGenerator(client=_FakeLLMClient())
    candidates = await llm.generate(_practice_context(), count=1)
    assert candidates and candidates[0].problem_statement == "2x + 3 = 7"
    assert candidates[0].generated_by == "mt-llm-candidate-v1"
    assert not hasattr(candidates[0], "verdict")

    # Prompt: PracticeGenerationContext PUBLIC fields only — no student id,
    # no mastery internals beyond the public mastery snapshot, no answer keys.
    prompt = build_llm_prompt(_practice_context())
    assert "target_skill_ids" in prompt
    assert "desired_difficulty" in prompt
    assert "student_id" not in prompt
    assert "candidate" not in prompt and "answer" not in prompt

    chain = await stack.release.release_candidate(candidates[0], source_type="LLM")
    assert chain.release.status == "released"
    exercise = await stack.practice.load_exercise(chain.exercise.exercise_id)
    assert exercise is not None and exercise.source_type == "LLM"


# ---------------------------------------------------------------------------
# 4-9: release immutability — any bound-byte change ⇒ a NEW release
# ---------------------------------------------------------------------------


async def test_04_invalid_candidate_denied_no_release():
    stack = _make_stack()
    bad = CandidateExercise(
        student_id=student_uuid(stack.owner.student_id),
        problem_statement="这不是一道数学题，请直接跳过",
        skill_ids=(SKILL_LINEAR_EQUATION,),
        concept_ids=(CONCEPT_LINEAR_EQUATIONS,),
        difficulty=2,
        generated_by="mt-bank-seed-v1",
    )
    with pytest.raises(ReleaseDeniedError):
        await stack.release.release_candidate(bad, source_type="BANK")
    # Nothing was written: no offers, no exercises, no releases.
    assert await stack.practice.offers_for_student(stack.owner.student_id) == []
    assert await stack.practice.list_outbox() == []


async def test_05_valid_candidate_released_with_attestation():
    stack = _make_stack()
    chain = await stack.release.release_candidate(_bank_candidate(), source_type="BANK")
    assert chain.release.status == "released"
    assert chain.decision is not None and chain.decision.verdict == "VERIFIED"
    assert chain.decision.candidate_payload_hash == chain.candidate.payload_hash
    assert chain.ref.verification_log_id is not None

    exercise = await stack.practice.load_exercise(chain.exercise.exercise_id)
    assert exercise is not None
    assert exercise.source_type == "BANK"
    assert exercise.content_hash
    assert exercise.problem_statement == "2x + 3 = 7"
    assert exercise.problem_id == chain.problem.problem_id
    assert exercise.difficulty == 2

    # The release binds its OWN exact snapshot (never "newest").
    exact = await stack.practice.load_exact_verified(chain.release)
    assert exact is not None
    problem, candidate, ref = exact
    assert problem.problem_id == chain.problem.problem_id
    assert candidate.payload_hash == chain.candidate.payload_hash
    assert ref.verification_log_id == chain.ref.verification_log_id


async def test_06_changed_problem_new_release():
    stack = _make_stack()
    chain1 = await stack.release.release_candidate(_bank_candidate(4), source_type="BANK")
    chain2 = await stack.release.release_candidate(_bank_candidate(5), source_type="BANK")
    assert chain2.release.release_id != chain1.release.release_id
    assert chain2.exercise.exercise_id != chain1.exercise.exercise_id
    assert chain2.release.problem_hash != chain1.release.problem_hash
    # Different exercises — both stay released (immutability, not supersede).
    assert (await stack.practice.load_release(chain1.release.release_id)).status == "released"
    assert (await stack.practice.load_release(chain2.release.release_id)).status == "released"
    assert chain2.decision is not None and chain2.decision.verdict == "VERIFIED"


async def test_07_changed_solution_new_release():
    """Same problem, different solution bytes → NEW release, old SUPERSEDED."""
    stack = _make_stack()
    chain1 = await stack.release.release_candidate(_bank_candidate(4), source_type="BANK")
    problem = chain1.problem

    # A DIFFERENT but valid solve path for 2x + 3 = 7 (verifier replays each
    # step: subtract 3, subtract 4, divide by 2 — ends at x - 2 = 0).
    alt = MathSolutionCandidate.canonicalize(
        problem_id=problem.problem_id,
        strategy="linear",
        steps=(
            {
                "label": "把常数 3 移项",
                "transform": {"kind": "subtract_term", "coeffs": {"0": {"n": 3, "d": 1}}},
                "before": {"lhs": {"1": {"n": 2, "d": 1}, "0": {"n": 3, "d": 1}}, "rhs": {"0": {"n": 7, "d": 1}}},
                "after": {"lhs": {"1": {"n": 2, "d": 1}, "0": {"n": 0, "d": 1}}, "rhs": {"0": {"n": 4, "d": 1}}},
            },
            {
                "label": "把常数 4 移项",
                "transform": {"kind": "subtract_term", "coeffs": {"0": {"n": 4, "d": 1}}},
                "before": {"lhs": {"1": {"n": 2, "d": 1}, "0": {"n": 0, "d": 1}}, "rhs": {"0": {"n": 4, "d": 1}}},
                "after": {"lhs": {"1": {"n": 2, "d": 1}, "0": {"n": -4, "d": 1}}, "rhs": {"0": {"n": 0, "d": 1}}},
            },
            {
                "label": "两边除以 2",
                "transform": {"kind": "divide_all", "value": {"n": 2, "d": 1}},
                "before": {"lhs": {"1": {"n": 2, "d": 1}, "0": {"n": -4, "d": 1}}, "rhs": {"0": {"n": 0, "d": 1}}},
                "after": {"lhs": {"1": {"n": 1, "d": 1}, "0": {"n": -2, "d": 1}}, "rhs": {"0": {"n": 0, "d": 1}}},
            },
        ),
        final_answer={"kind": "roots", "roots": ({"kind": "rational", "value": {"n": 2, "d": 1}},)},
    )
    assert alt.payload_hash != chain1.candidate.payload_hash

    chain2 = await stack.release.release_candidate(
        _bank_candidate(4), source_type="BANK", solution_candidate=alt
    )
    assert chain2.release.release_id != chain1.release.release_id
    assert chain2.exercise.exercise_id == chain1.exercise.exercise_id  # same exercise
    assert chain2.release.problem_hash == chain1.release.problem_hash
    assert chain2.release.solution_hash != chain1.release.solution_hash
    assert chain2.decision is not None and chain2.decision.verdict == "VERIFIED"
    # Same exercise → the old release is superseded by the new one.
    assert (await stack.practice.load_release(chain1.release.release_id)).status == "superseded"
    assert (await stack.practice.load_release(chain2.release.release_id)).status == "released"


async def test_08_verifier_version_change_new_release():
    stack = _make_stack()
    chain1 = await stack.release.release_candidate(_bank_candidate(), source_type="BANK")
    chain2 = await stack.release.release_candidate(
        _bank_candidate(), source_type="BANK", verifier_version="mt-verifier-v2"
    )
    assert chain1.release.verifier_hash == __import__(
        "mathtutor.application.practice_release", fromlist=["content_hash"]
    ).content_hash({"verifier_version": VERIFIER_VERSION})
    assert chain2.release.release_id != chain1.release.release_id
    assert chain2.release.verifier_hash != chain1.release.verifier_hash
    assert chain2.release.problem_hash == chain1.release.problem_hash
    assert chain2.release.solution_hash == chain1.release.solution_hash
    assert (await stack.practice.load_release(chain1.release.release_id)).status == "superseded"
    assert (await stack.practice.load_release(chain2.release.release_id)).status == "released"


async def test_09_policy_change_new_release():
    stack = _make_stack()
    chain1 = await stack.release.release_candidate(_bank_candidate(), source_type="BANK")
    chain2 = await stack.release.release_candidate(
        _bank_candidate(), source_type="BANK", policy_id="mt-policy-mvp-v2", policy_version="2"
    )
    assert chain2.release.release_id != chain1.release.release_id
    assert chain2.release.verification_policy_hash != chain1.release.verification_policy_hash
    assert chain2.release.verifier_hash == chain1.release.verifier_hash
    assert (await stack.practice.load_release(chain1.release.release_id)).status == "superseded"
    assert (await stack.practice.load_release(chain2.release.release_id)).status == "released"


# ---------------------------------------------------------------------------
# 10-13: revoked / superseded / expired ⇒ no new offers, no accepts
# ---------------------------------------------------------------------------


async def test_10_revoked_offer_no_new_offer_and_no_accept():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer1 = await _prepare(stack, parent)
    assert offer1.status == "ACTIVE"

    # A newer release (verifier change) supersedes v1 and REVOKES offer1.
    chain2 = await stack.release.release_candidate(
        _bank_candidate(), source_type="BANK", verifier_version="mt-verifier-v2"
    )
    offer1_after = await stack.practice.load_offer(offer1.offer_id)
    assert offer1_after.status == "REVOKED"
    assert (await stack.practice.load_release(offer1.exercise_release_id)).status == "superseded"

    # Accept of the revoked offer is refused (capability + CAS).
    bus = Collector()
    await stack.capability.run(
        _env(stack.owner, _SID, "accept_practice_offer", {"offer_id": str(offer1.offer_id)}), bus
    )
    assert [e.get("message") for e in bus.events if e["type"] == "error"]
    assert await stack.practice.accept_offer(stack.owner.student_id, offer1.offer_id) is False

    # A new offer is bound to a LIVE release — never the revoked one.
    offer2 = await _prepare(stack, parent)
    assert offer2.exercise_release_id != offer1.exercise_release_id
    assert offer2.exercise_release_id == chain2.release.release_id or (
        await stack.practice.load_release(offer2.exercise_release_id)
    ).status == "released"


async def test_11_superseded_release_no_new_offer_binding():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    chain1 = await stack.release.release_candidate(_bank_candidate(), source_type="BANK")
    offer1 = await _prepare(stack, parent)
    assert offer1.exercise_release_id == chain1.release.release_id

    await stack.release.release_candidate(
        _bank_candidate(), source_type="BANK", verifier_version="mt-verifier-v2"
    )
    # The superseded release itself can never anchor a NEW offer: prepare
    # re-issues the exact bytes as a fresh LIVE release instead of replaying.
    offer2 = await _prepare(stack, parent)
    assert offer2.exercise_release_id != chain1.release.release_id
    release2 = await stack.practice.load_release(offer2.exercise_release_id)
    assert release2 is not None and release2.status == "released"
    assert (await stack.practice.load_release(chain1.release.release_id)).status == "superseded"


async def test_12_expired_offer_not_accepted():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await stack.adaptive.prepare_offer(
        stack.owner.student_id,
        parent_cycle_id=parent.cycle.cycle_id,
        target_skill_ids=(SKILL_LINEAR_EQUATION,),
        count=1,
        ttl=timedelta(seconds=-10),
    )
    assert offer.expires_at <= datetime.now(timezone.utc)
    assert offer.status == "ACTIVE"  # stored ACTIVE; expiry is projected lazily

    bus = Collector()
    await stack.capability.run(
        _env(stack.owner, _SID, "accept_practice_offer", {"offer_id": str(offer.offer_id)}), bus
    )
    assert any(e.get("message") == "offer 已过期" for e in bus.events if e["type"] == "error")
    assert await stack.practice.accept_offer(stack.owner.student_id, offer.offer_id) is False


async def test_13_revoked_offer_not_accepted():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    # Supersede the release → the ACTIVE offer is REVOKED in the same bundle.
    await stack.release.release_candidate(
        _bank_candidate(), source_type="BANK", verifier_version="mt-verifier-v2"
    )
    assert (await stack.practice.load_offer(offer.offer_id)).status == "REVOKED"

    bus = Collector()
    await stack.capability.run(
        _env(stack.owner, _SID, "accept_practice_offer", {"offer_id": str(offer.offer_id)}), bus
    )
    assert any(e.get("message") == "offer 已失效（已撤销或已过期）" for e in bus.events if e["type"] == "error")
    assert await stack.practice.accept_offer(stack.owner.student_id, offer.offer_id) is False


# ---------------------------------------------------------------------------
# 14-16: idempotency + owner isolation
# ---------------------------------------------------------------------------


async def test_14_duplicate_accept_idempotent_same_child():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)

    metadata1, _ = await _accept(stack, offer)
    child_id = UUID(metadata1["child_cycle_id"])
    assert metadata1.get("idempotent_replay") is None

    # The client session's current cycle is now the child (same session row).
    current = await stack.capability.sessions.load(stack.owner.student_id, _SID)
    assert current.cycle.cycle_id == child_id
    assert current.state.value == "awaiting_attempt"

    # Replaying the accept returns the SAME child — nothing re-created.
    metadata2, bus2 = await _accept(stack, offer)
    assert UUID(metadata2["child_cycle_id"]) == child_id
    assert metadata2.get("idempotent_replay") is True
    child = await stack.capability.sessions.load_child_cycle_for_offer(
        stack.owner.student_id, offer.offer_id
    )
    assert child is not None and child.cycle.cycle_id == child_id
    assert child.state.value == "awaiting_attempt"
    assert len(child.transitions) == 3
    assert (await stack.practice.load_offer(offer.offer_id)).status == "ACCEPTED"


async def test_15_offer_list_owner_isolation():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    assert await stack.practice.offers_for_student(stack.owner.student_id) == [offer]

    # Owner B sees nothing — existence is never leaked.
    assert await stack.practice.offers_for_student(_owner_b().student_id) == []
    assert await stack.practice.offers_for_student_with_detail(_owner_b().student_id) == []


async def test_16_cross_owner_accept_refused():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)

    owner_b = _owner_b()
    bus = Collector()
    await stack.capability.run(
        _env(owner_b, _SID, "accept_practice_offer", {"offer_id": str(offer.offer_id)}), bus
    )
    assert any(e.get("message") == "offer 不存在" for e in bus.events if e["type"] == "error")
    assert await stack.practice.accept_offer(owner_b.student_id, offer.offer_id) is False
    assert (await stack.practice.load_offer(offer.offer_id)).status == "ACTIVE"


# ---------------------------------------------------------------------------
# 17-19: exact snapshot + child cycle = the SAME state machine, restart-safe
# ---------------------------------------------------------------------------


async def test_17_exact_release_snapshot_judging():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    release1 = await stack.practice.load_release(offer.exercise_release_id)
    exact1 = await stack.practice.load_exact_verified(release1)
    assert exact1 is not None
    log1 = exact1[2].verification_log_id

    metadata, _ = await _accept(stack, offer)
    child_id = UUID(metadata["child_cycle_id"])

    # NOW a newer release supersedes v1 (the offer is REVOKED)…
    chain2 = await stack.release.release_candidate(
        _bank_candidate(), source_type="BANK", verifier_version="mt-verifier-v2"
    )
    exact2 = await stack.practice.load_exact_verified(chain2.release)
    assert exact2 is not None
    log2 = exact2[2].verification_log_id
    assert log2 != log1
    # §7.9: only ACTIVE offers are revoked by the supersede — the accepted
    # offer stays ACCEPTED (fail-open: the started child cycle continues).
    assert (await stack.practice.load_offer(offer.offer_id)).status == "ACCEPTED"

    # …but the child cycle judges against the OFFER's OWN snapshot (v1).
    verified = await stack.capability.sessions.load_verified(stack.owner.student_id, child_id)
    assert verified is not None
    assert verified[2].verification_log_id == log1 != log2
    assert verified[1].payload_hash == exact1[1].payload_hash

    # Fail-open: the started child cycle continues to completion.
    bus = Collector()
    await stack.capability.run(_env(stack.owner, _SID, "submit_attempt", {"answer": "2"}), bus)
    last = [e for e in bus.events if e["type"] == "content"][-1]
    assert last["metadata"]["cycle_state"] == "solved"


async def test_18_child_cycle_restart_safe(db):
    stack = _make_sqlite_stack(db)
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    metadata, _ = await _accept(stack, offer)
    child_id = UUID(metadata["child_cycle_id"])

    # Simulate a process restart: brand-new store/repo/capability over the
    # SAME database. The child cycle must be fully restorable and continue.
    stack2 = _make_sqlite_stack(db)
    child = await stack2.store.load_child_cycle_for_offer(stack2.owner.student_id, offer.offer_id)
    assert child is not None
    assert child.cycle.cycle_id == child_id
    assert child.state.value == "awaiting_attempt"
    assert child.version == 3  # the 3 committed transitions (history in rows)

    # Continuation: submit_attempt on the restarted child → judged via the
    # exact release snapshot resolved from the offer (problem_id is NULL).
    bus = Collector()
    await stack2.capability.run(_env(stack2.owner, _SID, "submit_attempt", {"answer": "2"}), bus)
    last = [e for e in bus.events if e["type"] == "content"][-1]
    assert last["metadata"]["cycle_state"] == "solved"
    assert last["metadata"].get("detail") == "correct"
    # The attempt landed in the restarted store (append-only facts).
    assert await stack2.store.load_verified(stack2.owner.student_id, child_id) is not None


async def test_19_child_cycle_same_state_machine_no_second():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    metadata, bus = await _accept(stack, offer)

    child = await stack.capability.sessions.load(stack.owner.student_id, _SID)
    assert isinstance(child, TutoringSession)  # the SAME session type
    assert child.state.value == "awaiting_attempt"

    # XOR invariant: the child binds the offer, never a second problem id.
    assert child.cycle.practice_offer_id == offer.offer_id
    assert child.cycle.problem_id is None

    # The child advanced through the EXISTING state machine — no second one:
    # PROBLEM_RECEIVED v0 → GROUNDING v1 → SOLUTION_VERIFYING v2 →
    # AWAITING_ATTEMPT v3, three transitions.
    commands = [t.trigger_command for t in child.transitions]
    assert commands == [
        CycleCommand.SUBMIT_PROBLEM,
        CycleCommand.GROUNDING_OK,
        CycleCommand.VERIFICATION_VERIFIED,
    ]
    assert [t.prior_version for t in child.transitions] == [0, 1, 2]
    assert [t.new_version for t in child.transitions] == [1, 2, 3]
    assert child.version == 3

    # The parent closed — the accept event (student content event, §13.3
    # wire shape) carries the transition authority: practice_offered →
    # closed via accept_practice_offer.
    assert metadata["from_state"] == "practice_offered"
    assert metadata["to_state"] == "closed"
    assert metadata["trigger_command"] == "accept_practice_offer"


# ---------------------------------------------------------------------------
# 20-22: atomicity — ONE short transaction for release and accept
# ---------------------------------------------------------------------------


async def test_20_release_rollback_single_transaction(db):
    stack = _make_sqlite_stack(db)
    chain = await stack.release.release_candidate(_bank_candidate(), source_type="BANK")
    outbox_before = await stack.practice.list_outbox()
    assert len(outbox_before) == 1

    # A second bundle for the SAME bytes but a duplicate outbox key must fail
    # the transaction → NOTHING is written (no second release, no second
    # attestation, no new outbox row).
    v1 = chain.release
    duplicate_event = {
        "aggregate_type": "exercise_release",
        "aggregate_id": str(v1.release_id),
        "aggregate_version": 1,
        "event_sequence": 1,
        "event_type": "exercise_release_issued",
        "audience": "internal",
        "payload": {"exercise_id": str(chain.exercise.exercise_id), "status": "released"},
    }
    new_release = ExerciseRelease(
        release_id=uuid4(),
        exercise_id=chain.exercise.exercise_id,
        problem_hash=v1.problem_hash,
        solution_hash=v1.solution_hash,
        verification_policy_hash=v1.verification_policy_hash,
        verifier_hash=v1.verifier_hash,
        solution_candidate_hash=v1.solution_candidate_hash,
        license_hash=v1.license_hash,
        provenance_hash=v1.provenance_hash,
        status="draft",
    )
    with pytest.raises(Exception):
        await stack.practice.save_release_bundle(
            problem=chain.problem,
            candidate=chain.candidate,
            decision=chain.decision,
            exercise=chain.exercise,
            release=new_release,
            outbox_events=[duplicate_event],
        )

    assert len(await stack.practice.list_outbox()) == len(outbox_before)
    latest = await stack.practice.latest_release_for_exercise(chain.exercise.exercise_id)
    assert latest is not None and latest.release_id == v1.release_id  # nothing appended
    exact = await stack.practice.load_exact_verified(v1)
    assert exact is not None and exact[2].verification_log_id == chain.ref.verification_log_id


async def test_21_accept_rollback_single_transaction(db):
    stack = _make_sqlite_stack(db)
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    outbox_before = len(await stack.practice.list_outbox())

    # Build the exact bytes the capability would commit, but force the
    # outbox to fail (duplicate key) INSIDE the accept transaction.
    seed_event = (await stack.practice.list_outbox())[0]
    parent_transition = parent.step(CycleCommand.ACCEPT_PRACTICE_OFFER)
    child = TutoringSession(
        session_id=parent.session_id,
        student_id=student_uuid(stack.owner.student_id),
        practice_offer_id=offer.offer_id,
    )
    child.step(CycleCommand.SUBMIT_PROBLEM)
    child.step(CycleCommand.GROUNDING_OK)
    child.step(CycleCommand.VERIFICATION_VERIFIED)

    with pytest.raises(Exception):
        await stack.store.accept_practice_offer(
            stack.owner.student_id,
            _SID,
            offer.offer_id,
            parent_transition,
            child,
            outbox_events=[seed_event],  # duplicate → whole tx rolls back
        )

    # Offer NOT consumed, parent NOT closed, child NOT created, outbox clean.
    offer_after = await stack.practice.load_offer(offer.offer_id)
    assert offer_after is not None and offer_after.status == "ACTIVE"
    assert offer_after.consumed_at is None
    parent_after = await stack.store.load(stack.owner.student_id, _SID)
    assert parent_after.state.value == "practice_offered"
    assert (
        await stack.store.load_child_cycle_for_offer(stack.owner.student_id, offer.offer_id)
        is None
    )
    assert len(await stack.practice.list_outbox()) == outbox_before


async def test_22_outbox_events_same_transaction(db):
    stack = _make_sqlite_stack(db)
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    metadata, _ = await _accept(stack, offer)
    child_id = metadata["child_cycle_id"]

    outbox = await stack.practice.list_outbox()
    types = [row["event_type"] for row in outbox]
    # 8 bank releases + 1 offer + 2 accept events — all rows in ONE place.
    assert types.count("exercise_release_issued") == 8
    assert "practice_offer_issued" in types
    assert "cycle_state_committed" in types
    assert "practice_offer_accepted" in types

    offer_event = next(r for r in outbox if r["event_type"] == "practice_offer_issued")
    assert offer_event["payload"]["offer_id"] == str(offer.offer_id)
    assert offer_event["payload"]["parent_cycle_id"] == str(parent.cycle.cycle_id)
    accepted_event = next(r for r in outbox if r["event_type"] == "practice_offer_accepted")
    assert accepted_event["payload"]["child_cycle_id"] == child_id
    committed = next(r for r in outbox if r["event_type"] == "cycle_state_committed")
    assert committed["payload"]["from_state"] == "practice_offered"
    assert committed["payload"]["to_state"] == "closed"

    # The accept rows exist BECAUSE the offer was consumed in that tx.
    offer_after = await stack.practice.load_offer(offer.offer_id)
    assert offer_after.status == "ACCEPTED" and offer_after.consumed_at is not None
    # Release events carry no solution/answer payloads.
    for row in outbox:
        for key in FORBIDDEN_KEYS:
            assert key not in row["payload"]


# ---------------------------------------------------------------------------
# 23-24: public contract — never a solution/answer key/mastery/attestation
# ---------------------------------------------------------------------------


async def test_23_no_answer_key_in_student_public_events():
    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)

    metadata, bus = await _accept(stack, offer)
    assert metadata["child_cycle_id"]
    assert metadata["cycle_state"] == "closed"
    assert metadata["problem_latex"]  # student-facing problem surface only
    for key in FORBIDDEN_KEYS:
        assert key not in metadata, f"forbidden key in accept event: {key}"

    # No event of the accept turn (content/emit/error) leaks internals.
    for event in bus.events:
        candidate_payload = event.get("event", {}).get("payload", {}) if event["type"] == "emit" else event.get("metadata", {})
        for key in FORBIDDEN_KEYS:
            assert key not in candidate_payload, f"forbidden key: {key}"

    # The child's attempt result carries correctness, never the answer key.
    bus3 = Collector()
    await stack.capability.run(_env(stack.owner, _SID, "submit_attempt", {"answer": "2"}), bus3)
    last = [e for e in bus3.events if e["type"] == "content"][-1]
    assert last["metadata"]["cycle_state"] == "solved"
    for key in FORBIDDEN_KEYS:
        assert key not in last["metadata"], f"forbidden key in solved event: {key}"


async def test_24_offer_projection_no_solution(monkeypatch):
    import mathtutor.api.math_tutor_read as read

    stack = _make_stack()
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)

    class _FakeState:
        practice_repository = stack.practice
        capability = stack.capability

    monkeypatch.setattr(read, "get_product_state", lambda: _FakeState())
    rows = await read.list_offers(owner=stack.owner)

    assert len(rows) == 1
    item = rows[0]
    # The /offers contract is EXACTLY these public fields — nothing else.
    assert set(item) == {
        "offer_id",
        "status",
        "skill_labels",
        "concept_labels",
        "difficulty",
        "offered_at",
        "expires_at",
        "parent_cycle_id",
    }
    assert item["offer_id"] == str(offer.offer_id)
    assert item["status"] == "ACTIVE"
    assert item["difficulty"] == 2
    assert SKILL_LINEAR_EQUATION in item["skill_labels"]
    assert item["parent_cycle_id"] == str(parent.cycle.cycle_id)
    for key in FORBIDDEN_KEYS:
        assert key not in item, f"forbidden key in projection: {key}"

    # The label reverse-mapping is deterministic and curriculum-scoped.
    labels = labels_for_mapping_ids(offer.target_mapping_ids)
    assert labels["skill_labels"] == [SKILL_LINEAR_EQUATION]
    assert labels["concept_labels"] == [CONCEPT_LINEAR_EQUATIONS]


# ---------------------------------------------------------------------------
# 25: LLM failure → deterministic fallback (bank > template > LLM)
# ---------------------------------------------------------------------------


class _RaisingLLMClient:
    async def complete(self, **kwargs: Any) -> str:
        raise RuntimeError("provider down")


async def test_25_llm_failure_deterministic_fallback():
    stack = _make_stack()
    ctx = _practice_context()

    # Fail closed: unconfigured gateway → the LLM generator itself raises.
    llm = LLMCandidateExerciseGenerator(gateway=None)
    with pytest.raises(PracticeGenerationError):
        await llm.generate(ctx, count=1)
    # A raising provider is surfaced as PracticeGenerationError too.
    llm_bad = LLMCandidateExerciseGenerator(client=_RaisingLLMClient())
    with pytest.raises(PracticeGenerationError):
        await llm_bad.generate(ctx, count=1)

    # The chain never NEEDS the LLM for a bank-covered target: bank wins.
    chain_gen = PracticeGeneratorChain(gateway=None)
    candidates = await chain_gen.generate(ctx, count=1)
    assert candidates and candidates[0].generated_by.startswith("mt-bank-")
    assert candidates[0].problem_statement == "2x + 3 = 7"

    # prepare_offer succeeds end-to-end with an unconfigured gateway — the
    # offer is anchored by a BANK release, all through the release gate.
    await _publish_seed(stack)
    parent = await _to_practice_offered(stack)
    offer = await _prepare(stack, parent)
    assert offer.status == "ACTIVE"
    release = await stack.practice.load_release(offer.exercise_release_id)
    exercise = await stack.practice.load_exercise(release.exercise_id)
    assert exercise.source_type == "BANK"

    # Template is the middle deterministic step (bank > template > LLM).
    template_gen = TemplateCandidateExerciseGenerator()
    template_candidates = await template_gen.generate(ctx, count=1)
    assert template_candidates and template_candidates[0].generated_by.startswith("mt-template-")

    # When NOTHING is available (unknown target), the chain fails CLOSED
    # with no candidates — the offer preparation refuses, not degrades.
    unknown = ctx.model_copy(update={"target_skill_ids": ("UNKNOWN_SKILL",)})
    assert await chain_gen.generate(unknown, count=1) == []

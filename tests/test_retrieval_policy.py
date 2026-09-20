"""RetrievalPolicy matrix tests (§37 POLICY group).

The policy matrix is the frozen contract between intents and knowledge
sources: LLM consumers never choose what to read — the plan does.

SCOPE REMINDER (audit D13): the matrix governs the structured
ContextAssembler path only. Chat and knowledge-QA turns are gated by the
conversation binding instead and never consult it. The reachability guard at
the bottom keeps that boundary from silently widening back into
"this looks like it governs all retrieval".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mathtutor.domain.retrieval_policy import (
    DEFAULT_RETRIEVAL_POLICY,
    PRODUCTION_INTENTS,
    RetrievalDecision,
    RetrievalIntent,
    RetrievalPlan,
    RetrievalPolicy,
    RetrievalSource,
)

_ALL_SOURCES = set(RetrievalSource)


def test_generate_practice_requires_four_sources():
    plan = DEFAULT_RETRIEVAL_POLICY.resolve(RetrievalIntent.GENERATE_PRACTICE)
    assert set(plan.required_sources()) == {
        RetrievalSource.STUDENT_MODEL,
        RetrievalSource.CURRICULUM,
        RetrievalSource.MISCONCEPTION_HISTORY,
        RetrievalSource.RECENT_ATTEMPTS,
    }
    assert set(plan.optional_sources()) == {
        RetrievalSource.PERSONAL_MEMORY,
        RetrievalSource.USER_DOCUMENTS,
    }


def test_generate_error_review_requires_four_sources():
    plan = DEFAULT_RETRIEVAL_POLICY.resolve(RetrievalIntent.GENERATE_ERROR_REVIEW)
    assert set(plan.required_sources()) == {
        RetrievalSource.STUDENT_MODEL,
        RetrievalSource.CURRICULUM,
        RetrievalSource.MISCONCEPTION_HISTORY,
        RetrievalSource.RECENT_ATTEMPTS,
    }


def test_use_my_document_requires_user_documents():
    plan = DEFAULT_RETRIEVAL_POLICY.resolve(RetrievalIntent.USE_MY_DOCUMENT)
    assert plan.resolve(RetrievalSource.USER_DOCUMENTS) is RetrievalDecision.REQUIRED
    assert plan.resolve(RetrievalSource.CURRICULUM) is RetrievalDecision.REQUIRED
    # Student model is pedagogy-optional for document use.
    assert plan.resolve(RetrievalSource.STUDENT_MODEL) is RetrievalDecision.OPTIONAL


def test_unlisted_source_defaults_to_forbidden():
    # SOLVE_PROBLEM has no misconception/attempt row — forbidden, never permissive.
    plan = DEFAULT_RETRIEVAL_POLICY.resolve(RetrievalIntent.SOLVE_PROBLEM)
    assert plan.resolve(RetrievalSource.MISCONCEPTION_HISTORY) is RetrievalDecision.FORBIDDEN
    assert plan.resolve(RetrievalSource.RECENT_ATTEMPTS) is RetrievalDecision.FORBIDDEN
    assert plan.is_forbidden(RetrievalSource.MISCONCEPTION_HISTORY)


def test_required_and_optional_partition_exhaustively():
    for intent in RetrievalIntent:
        plan = DEFAULT_RETRIEVAL_POLICY.resolve(intent)
        required = set(plan.required_sources())
        optional = set(plan.optional_sources())
        forbidden = {
            source for source in _ALL_SOURCES if plan.is_forbidden(source)
        }
        assert required.isdisjoint(optional)
        assert required.isdisjoint(forbidden)
        assert optional.isdisjoint(forbidden)
        assert required | optional | forbidden == _ALL_SOURCES


def test_plan_is_frozen_data():
    plan = DEFAULT_RETRIEVAL_POLICY.resolve(RetrievalIntent.GENERATE_PRACTICE)
    decisions = plan.decisions
    with pytest.raises(TypeError):
        plan.decisions[RetrievalSource.STUDENT_MODEL] = RetrievalDecision.FORBIDDEN  # type: ignore[index]
    # Even a mutable copy cannot change the original plan's decisions.
    assert decisions[RetrievalSource.STUDENT_MODEL] is RetrievalDecision.REQUIRED


def test_policy_version_is_stable():
    assert RetrievalPolicy.POLICY_VERSION == "mt-retrieval-policy-v1"


def test_unknown_intent_raises():
    with pytest.raises(ValueError):
        DEFAULT_RETRIEVAL_POLICY.resolve("not_an_intent")  # type: ignore[arg-type]


def test_resolved_plan_preserves_intent():
    plan: RetrievalPlan = DEFAULT_RETRIEVAL_POLICY.resolve(RetrievalIntent.REQUEST_HINT)
    assert plan.intent is RetrievalIntent.REQUEST_HINT


# --------------------------------------------------------------- D13 scope


def _intents_referenced_in_src() -> set[str]:
    """Every RetrievalIntent member named anywhere under src/.

    Scans the source tree rather than trusting a hand-maintained list: the
    whole failure mode being guarded against is a row that LOOKS reachable.
    """
    root = Path(__file__).resolve().parents[1] / "src"
    pattern = re.compile(r"RetrievalIntent\.([A-Z_]+)")
    found: set[str] = set()
    for path in root.rglob("*.py"):
        if path.name == "retrieval_policy.py":
            continue  # the matrix itself names every member
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


def test_only_declared_intents_are_reachable():
    """PRODUCTION_INTENTS must equal what src/ actually resolves.

    Adding a new production call site without declaring it here fails this
    test; so does declaring a row production-reachable that nothing resolves.
    """
    declared = {intent.name for intent in PRODUCTION_INTENTS}
    referenced = _intents_referenced_in_src()

    assert referenced == declared, (
        "RetrievalPolicy scope drift.\n"
        f"  resolved in src/ but not declared: {sorted(referenced - declared)}\n"
        f"  declared but never resolved:      {sorted(declared - referenced)}"
    )


def test_use_my_document_is_not_production_reachable():
    """The one REQUIRED-documents row must not be cited as product behaviour.

    USE_MY_DOCUMENT sets USER_DOCUMENTS to REQUIRED, so reading the matrix
    alone implies the policy forces document retrieval for "use my document"
    questions. No production path resolves it (tests/test_retrieval_policy.py
    is its only caller); those questions are answered by the chat path.
    """
    assert RetrievalIntent.USE_MY_DOCUMENT not in PRODUCTION_INTENTS

    plan = DEFAULT_RETRIEVAL_POLICY.resolve(RetrievalIntent.USE_MY_DOCUMENT)
    assert plan.resolve(RetrievalSource.USER_DOCUMENTS) is RetrievalDecision.REQUIRED
    # ...and yet nothing in src/ asks for it.
    assert "USE_MY_DOCUMENT" not in _intents_referenced_in_src()


def test_chat_and_knowledge_paths_do_not_consult_the_matrix():
    """D13 boundary: the conversational paths choose sources elsewhere."""
    root = Path(__file__).resolve().parents[1] / "src" / "mathtutor" / "application"
    for module in ("chat_documents.py", "knowledge.py", "knowledge_qa.py", "knowledge_tools.py"):
        text = (root / module).read_text(encoding="utf-8")
        assert "RetrievalPolicy" not in text, f"{module} must not gate on RetrievalPolicy"
        assert "retrieval_policy" not in text, f"{module} must not import retrieval_policy"

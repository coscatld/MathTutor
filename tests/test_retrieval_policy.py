"""RetrievalPolicy matrix tests (§37 POLICY group).

The policy matrix is the frozen contract between intents and knowledge
sources: LLM consumers never choose what to read — the plan does.
"""

from __future__ import annotations

import pytest

from mathtutor.domain.retrieval_policy import (
    DEFAULT_RETRIEVAL_POLICY,
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

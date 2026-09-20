"""PracticeRetrievalPolicy — the deterministic source matrix for LLM consumers.

SCOPE (read this before assuming the matrix governs "retrieval"):

This matrix governs the **structured ContextAssembler path only** — the
actions that hand a typed :class:`AssembledContext` to a writer:

    GENERATE_PRACTICE    adaptive_practice.py:180
    REQUEST_HINT         controller.py:2243   (GIVE_HINT action)
    EXPLAIN_CONCEPT      controller.py:2245   (EXPLAIN_CONCEPT action)

It does NOT govern the conversational retrieval paths. Chat turns are
served by ``ChatDocumentContext`` and knowledge-QA turns by
``KnowledgeTools``; both are gated by the conversation binding
(``config.mode`` / ``hints_only``) plus the conversation document scope,
and neither consults this matrix. See docs/CURRENT_STATE_RAG_AUDIT.md §6.5.

:data:`PRODUCTION_INTENTS` lists the rows a product request can actually
resolve. The remaining rows are exercised only by tests; they are retained
because the matrix is exhaustive by construction, but nothing may cite them
as evidence that this policy drives the product.

Decision semantics:

- ``REQUIRED``  — the source MUST load; an unavailable required source
  fails the operation closed (RequiredSourceUnavailableError at the
  assembler). REQUIRED sources cannot be dropped by token budget.
- ``OPTIONAL``  — a ContextRouter may decide to actually retrieve it.
  USER PERMISSION OUTRANKS THE ROUTER: a source disabled by the user
  (``retrieval_enabled=false``) is never retrieved, whatever the router
  or the LLM asks for.
- ``FORBIDDEN`` — structurally absent: the source is not loaded at all,
  and no LLM request can override this (the plan is frozen data).

Any source not listed in an intent's row defaults to FORBIDDEN — the
matrix is exhaustive by construction, never permissive by omission.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class RetrievalSource(str, Enum):
    STUDENT_MODEL = "student_model"
    CURRICULUM = "curriculum"
    MISCONCEPTION_HISTORY = "misconception_history"
    RECENT_ATTEMPTS = "recent_attempts"
    PERSONAL_MEMORY = "personal_memory"
    USER_DOCUMENTS = "user_documents"


class RetrievalDecision(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


class RetrievalIntent(str, Enum):
    SOLVE_PROBLEM = "solve_problem"
    REQUEST_HINT = "request_hint"
    EXPLAIN_CONCEPT = "explain_concept"
    GENERATE_PRACTICE = "generate_practice"
    GENERATE_ERROR_REVIEW = "generate_error_review"
    USE_MY_DOCUMENT = "use_my_document"


#: Rows a product request can actually resolve, with the call site that does
#: it. Anything outside this set is TEST_ONLY — pinned by
#: tests/test_retrieval_policy.py::test_only_declared_intents_are_reachable.
#:
#: USE_MY_DOCUMENT is deliberately NOT here. It is the one row that makes
#: USER_DOCUMENTS REQUIRED, so reading the matrix alone suggests the policy
#: forces document retrieval for "use my document" questions. No production
#: path resolves it; the chat path answers those through ChatDocumentContext.
PRODUCTION_INTENTS: frozenset[RetrievalIntent] = frozenset(
    {
        RetrievalIntent.GENERATE_PRACTICE,
        RetrievalIntent.REQUEST_HINT,
        RetrievalIntent.EXPLAIN_CONCEPT,
    }
)


# The authoritative policy matrix (design spec §21). Rows are intents,
# columns are sources; a missing cell is FORBIDDEN.
_POLICY_MATRIX: Mapping[RetrievalIntent, Mapping[RetrievalSource, RetrievalDecision]] = {
    RetrievalIntent.SOLVE_PROBLEM: {
        RetrievalSource.STUDENT_MODEL: RetrievalDecision.OPTIONAL,
        RetrievalSource.CURRICULUM: RetrievalDecision.REQUIRED,
        RetrievalSource.PERSONAL_MEMORY: RetrievalDecision.OPTIONAL,
        RetrievalSource.USER_DOCUMENTS: RetrievalDecision.OPTIONAL,
    },
    RetrievalIntent.REQUEST_HINT: {
        RetrievalSource.STUDENT_MODEL: RetrievalDecision.REQUIRED,
        RetrievalSource.CURRICULUM: RetrievalDecision.REQUIRED,
        RetrievalSource.PERSONAL_MEMORY: RetrievalDecision.OPTIONAL,
        RetrievalSource.USER_DOCUMENTS: RetrievalDecision.OPTIONAL,
    },
    RetrievalIntent.EXPLAIN_CONCEPT: {
        RetrievalSource.STUDENT_MODEL: RetrievalDecision.OPTIONAL,
        RetrievalSource.CURRICULUM: RetrievalDecision.REQUIRED,
        RetrievalSource.PERSONAL_MEMORY: RetrievalDecision.OPTIONAL,
        RetrievalSource.USER_DOCUMENTS: RetrievalDecision.OPTIONAL,
    },
    RetrievalIntent.GENERATE_PRACTICE: {
        RetrievalSource.STUDENT_MODEL: RetrievalDecision.REQUIRED,
        RetrievalSource.CURRICULUM: RetrievalDecision.REQUIRED,
        RetrievalSource.MISCONCEPTION_HISTORY: RetrievalDecision.REQUIRED,
        RetrievalSource.RECENT_ATTEMPTS: RetrievalDecision.REQUIRED,
        RetrievalSource.PERSONAL_MEMORY: RetrievalDecision.OPTIONAL,
        RetrievalSource.USER_DOCUMENTS: RetrievalDecision.OPTIONAL,
    },
    RetrievalIntent.GENERATE_ERROR_REVIEW: {
        RetrievalSource.STUDENT_MODEL: RetrievalDecision.REQUIRED,
        RetrievalSource.CURRICULUM: RetrievalDecision.REQUIRED,
        RetrievalSource.MISCONCEPTION_HISTORY: RetrievalDecision.REQUIRED,
        RetrievalSource.RECENT_ATTEMPTS: RetrievalDecision.REQUIRED,
        RetrievalSource.PERSONAL_MEMORY: RetrievalDecision.OPTIONAL,
        RetrievalSource.USER_DOCUMENTS: RetrievalDecision.OPTIONAL,
    },
    RetrievalIntent.USE_MY_DOCUMENT: {
        # Student model: "according to pedagogy" → OPTIONAL (router may add it).
        RetrievalSource.STUDENT_MODEL: RetrievalDecision.OPTIONAL,
        RetrievalSource.CURRICULUM: RetrievalDecision.REQUIRED,
        RetrievalSource.PERSONAL_MEMORY: RetrievalDecision.OPTIONAL,
        RetrievalSource.USER_DOCUMENTS: RetrievalDecision.REQUIRED,
    },
}


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    """One resolved matrix row — frozen; no consumer (incl. LLM) can mutate it."""

    intent: RetrievalIntent
    decisions: Mapping[RetrievalSource, RetrievalDecision]

    def resolve(self, source: RetrievalSource) -> RetrievalDecision:
        return self.decisions.get(source, RetrievalDecision.FORBIDDEN)

    def required_sources(self) -> tuple[RetrievalSource, ...]:
        return tuple(
            source
            for source in RetrievalSource
            if self.resolve(source) is RetrievalDecision.REQUIRED
        )

    def optional_sources(self) -> tuple[RetrievalSource, ...]:
        return tuple(
            source
            for source in RetrievalSource
            if self.resolve(source) is RetrievalDecision.OPTIONAL
        )

    def is_forbidden(self, source: RetrievalSource) -> bool:
        return self.resolve(source) is RetrievalDecision.FORBIDDEN


class PracticeRetrievalPolicy:
    """Deterministic, versioned policy resolver over the matrix."""

    POLICY_VERSION = "mt-retrieval-policy-v1"

    def resolve(self, intent: RetrievalIntent) -> RetrievalPlan:
        row = _POLICY_MATRIX.get(intent)
        if row is None:
            raise ValueError(f"no retrieval policy row for intent {intent!r}")
        # Freeze per decision (read-only mapping) so nothing downstream —
        # LLM consumers included — can mutate the plan.
        return RetrievalPlan(intent=intent, decisions=MappingProxyType(dict(row)))


DEFAULT_PRACTICE_RETRIEVAL_POLICY = PracticeRetrievalPolicy()
# Compatibility for callers of the previous public name; production uses the
# scoped name. Matrix semantics and persisted policy version remain unchanged.
RetrievalPolicy = PracticeRetrievalPolicy
DEFAULT_RETRIEVAL_POLICY = DEFAULT_PRACTICE_RETRIEVAL_POLICY


__all__ = [
    "DEFAULT_RETRIEVAL_POLICY",
    "DEFAULT_PRACTICE_RETRIEVAL_POLICY",
    "PracticeRetrievalPolicy",
    "PRODUCTION_INTENTS",
    "RetrievalDecision",
    "RetrievalIntent",
    "RetrievalPlan",
    "RetrievalPolicy",
    "RetrievalSource",
]

"""RetrievalPolicy — the deterministic source matrix for LLM consumers.

Which knowledge sources may/ must feed a tutoring or practice LLM call is
decided HERE, not by the model. The LLM never chooses whether to read the
Student Model, misconception history or documents; the application service
resolves the policy, loads REQUIRED sources, optionally retrieves OPTIONAL
sources (router-decided), and only then calls the model via the assembled
typed context (ContextAssembler).

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


class RetrievalPolicy:
    """Deterministic, versioned policy resolver over the matrix."""

    POLICY_VERSION = "mt-retrieval-policy-v1"

    def resolve(self, intent: RetrievalIntent) -> RetrievalPlan:
        row = _POLICY_MATRIX.get(intent)
        if row is None:
            raise ValueError(f"no retrieval policy row for intent {intent!r}")
        # Freeze per decision (read-only mapping) so nothing downstream —
        # LLM consumers included — can mutate the plan.
        return RetrievalPlan(intent=intent, decisions=MappingProxyType(dict(row)))


DEFAULT_RETRIEVAL_POLICY = RetrievalPolicy()


__all__ = [
    "DEFAULT_RETRIEVAL_POLICY",
    "RetrievalDecision",
    "RetrievalIntent",
    "RetrievalPlan",
    "RetrievalPolicy",
    "RetrievalSource",
]

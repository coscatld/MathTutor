"""Phase 4 learning loop (pure, deterministic, no LLM, no UI).

Pipeline: ``parse_student_attempt`` -> ``verify_attempt`` -> ``diagnose``
-> ``EvidenceFactory.build_evidence`` -> ``project_student_state``, with
``MasteryEstimator`` as the versioned increment/decrement rule and the
repository persisting attempt / assessment / observation / evidence /
projection inside ONE short transaction (compare-and-set on
``projection_version``).

Every module in this package is pure computation: no transactions, no
network, no randomness in the math path. Mastery evidence is append-only;
the projection is always replayed from the same immutable facts.
"""

from __future__ import annotations

from mathtutor.learning.attempt_parser import (
    ParsedAttempt,
    interpret_attempt,
    parse_student_attempt,
)
from mathtutor.learning.attempt_verifier import (
    AttemptAssessment,
    Correctness,
    verify_attempt,
)
from mathtutor.learning.diagnosis import (
    RULES,
    MisconceptionObservation,
    RuleSpec,
    diagnose,
)
from mathtutor.learning.estimator import ESTIMATOR_VERSION, MasteryEstimator
from mathtutor.learning.evidence import (
    EVIDENCE_VERSION,
    EvidenceFactory,
    LearningEvidence,
    idempotency_key_for,
)
from mathtutor.learning.projection import (
    StudentStateProjection,
    project_student_state,
)
from mathtutor.learning.skills import (
    all_skill_ids,
    concept_for_skill,
    skill_for_problem,
    skill_for_problem_type,
)

__all__ = [
    "AttemptAssessment",
    "Correctness",
    "ESTIMATOR_VERSION",
    "EVIDENCE_VERSION",
    "EvidenceFactory",
    "LearningEvidence",
    "MasteryEstimator",
    "MisconceptionObservation",
    "ParsedAttempt",
    "RULES",
    "RuleSpec",
    "StudentStateProjection",
    "all_skill_ids",
    "concept_for_skill",
    "diagnose",
    "idempotency_key_for",
    "interpret_attempt",
    "parse_student_attempt",
    "project_student_state",
    "skill_for_problem",
    "skill_for_problem_type",
    "verify_attempt",
]

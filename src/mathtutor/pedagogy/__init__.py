"""Pedagogy — the teaching control chain (Phase 3).

    StagePolicy → PedagogyPlanner → SolutionDisclosureProjector
    → TutorWriter → TutorOutputGuard → StudentPublicEvent

The chain is a DATA boundary, not a prompt boundary: the writer only ever
sees the projected context; the guard verifies the final text; the student
serializer only accepts the typed public event.
"""

from __future__ import annotations

from mathtutor.pedagogy.disclosure import (
    DisclosedSolutionContext,
    SolutionDisclosureProjector,
)
from mathtutor.pedagogy.events import (
    FORBIDDEN_STUDENT_FIELDS,
    InternalEvent,
    StudentPublicEvent,
    serialize_student_event,
)
from mathtutor.pedagogy.exceptions import DisclosurePolicyViolation
from mathtutor.pedagogy.output_guard import (
    GuardedTutorUtterance,
    TutorOutputGuard,
)
from mathtutor.pedagogy.planner import CycleAssistance, PedagogyPlanner
from mathtutor.pedagogy.stage_policy import (
    HIGH_POLICY,
    MIDDLE_POLICY,
    PRIMARY_POLICY,
    STAGE_POLICIES,
    StagePolicy,
    policy_for_stage,
)
from mathtutor.pedagogy.tutor_writer import (
    LLMTutorWriter,
    PublicProblemView,
    TemplateTutorWriter,
    TutorWriter,
    TutorWriterCandidate,
)
from mathtutor.pedagogy.writer_settings import (
    MathTutorWriterSettings,
    load_math_tutor_writer_settings,
)

__all__ = [
    "CycleAssistance",
    "DisclosedSolutionContext",
    "DisclosurePolicyViolation",
    "FORBIDDEN_STUDENT_FIELDS",
    "GuardedTutorUtterance",
    "HIGH_POLICY",
    "InternalEvent",
    "LLMTutorWriter",
    "MIDDLE_POLICY",
    "PRIMARY_POLICY",
    "PedagogyPlanner",
    "PublicProblemView",
    "STAGE_POLICIES",
    "SolutionDisclosureProjector",
    "StagePolicy",
    "StudentPublicEvent",
    "TemplateTutorWriter",
    "TutorOutputGuard",
    "TutorWriter",
    "TutorWriterCandidate",
    "MathTutorWriterSettings",
    "load_math_tutor_writer_settings",
    "policy_for_stage",
    "serialize_student_event",
]

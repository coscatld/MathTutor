"""Domain contract of the K12 MathTutor vertical slice.

The five trust domains (design doc §1.3):

1. candidate solutions — :mod:`~mathtutor.domain.solution`
2. math facts — canonical problems & attestations — :mod:`~mathtutor.domain.problem`
3. teaching permissions — tutor actions & disclosure policy — :mod:`~mathtutor.domain.tutoring`
4. learning evidence — attempts & evidence — :mod:`~mathtutor.domain.attempt`, :mod:`~mathtutor.domain.student_state`
5. long-term student state — :mod:`~mathtutor.domain.student_state`

All hashes are server-owned (see :mod:`~mathtutor.domain.hashing`).
"""

from __future__ import annotations

from mathtutor.domain.attempt import AttemptAssessmentRef, AttemptSubmission, StudentAttempt
from mathtutor.domain.curriculum import CurriculumEdge, CurriculumNode, CurriculumVersion
from mathtutor.domain.practice import Exercise, ExerciseRelease
from mathtutor.domain.problem import MathProblem, ProblemGrounding, ProblemMappingRef
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    SolutionAttestation,
    VerificationCheck,
    VerificationDecision,
    VerifiedSolutionRef,
)
from mathtutor.domain.student_state import StudentState
from mathtutor.domain.tutoring import (
    CycleTransition,
    PracticeOffer,
    TutorAction,
    TutoringCycle,
)

__all__ = [
    "AttemptAssessmentRef",
    "AttemptSubmission",
    "CurriculumEdge",
    "CurriculumNode",
    "CurriculumVersion",
    "CycleTransition",
    "Exercise",
    "ExerciseRelease",
    "MathProblem",
    "MathSolutionCandidate",
    "PracticeOffer",
    "ProblemGrounding",
    "ProblemMappingRef",
    "SolutionAttestation",
    "StudentAttempt",
    "StudentState",
    "TutorAction",
    "TutoringCycle",
    "VerificationCheck",
    "VerificationDecision",
    "VerifiedSolutionRef",
]

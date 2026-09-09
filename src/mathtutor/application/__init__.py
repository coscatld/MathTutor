"""Application layer public API.

Imports are lazy so a focused infrastructure import cannot re-enter the
pedagogy/application packages while either is only partially initialized.
"""

from __future__ import annotations

from typing import Any

_SERVICE_EXPORTS = {"MathTutorApplicationService", "SubmitProblemResult"}
_STATE_EXPORTS = {
    "CycleCommand",
    "CycleState",
    "InvalidTransitionError",
    "TutoringSession",
    "VersionConflictError",
    "allowed_next_commands",
}


def __getattr__(name: str) -> Any:
    if name in _SERVICE_EXPORTS:
        from mathtutor.application import math_tutor_service

        return getattr(math_tutor_service, name)
    if name in _STATE_EXPORTS:
        from mathtutor.application import state_machine

        return getattr(state_machine, name)
    raise AttributeError(name)

__all__ = [
    "CycleCommand",
    "CycleState",
    "InvalidTransitionError",
    "MathTutorApplicationService",
    "SubmitProblemResult",
    "TutoringSession",
    "VersionConflictError",
    "allowed_next_commands",
]

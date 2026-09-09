"""Student-facing projection of tutor events.

Internal commands, state names and parser traces stay in logs. The UI
only receives UserMessage / AssistantMessage / a generic recovery notice.
"""

from __future__ import annotations

import re

from mathtutor.application.state_machine import STUDENT_TRANSITION_FAILURE

_COMMAND_ACK = re.compile(r"^命令\s+\w+\s+已确认")
_STATE_REJECT = re.compile(r"状态\s+\w+\s+不接受命令\s+\w+")
_INTERNAL_LEAK = re.compile(
    r"(submit_problem|clarify_problem|clarify_attempt|grounding_ok|"
    r"grounding_ambiguous|cycle_state|trigger_command|InvalidTransition)",
    re.IGNORECASE,
)


def project_assistant_message(text: str) -> str | None:
    """Return the student-visible assistant text, or None to drop the event."""
    compact = str(text or "").strip()
    if not compact:
        return None
    if _COMMAND_ACK.match(compact) or _STATE_REJECT.search(compact) or _INTERNAL_LEAK.search(compact):
        if _COMMAND_ACK.match(compact):
            return None
        return STUDENT_TRANSITION_FAILURE
    return compact


def project_turn_error(text: str) -> str:
    compact = str(text or "").strip()
    if not compact or _STATE_REJECT.search(compact) or _INTERNAL_LEAK.search(compact):
        return STUDENT_TRANSITION_FAILURE
    return compact


__all__ = [
    "project_assistant_message",
    "project_turn_error",
    "STUDENT_TRANSITION_FAILURE",
]

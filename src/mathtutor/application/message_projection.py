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


def command_message_label(command: str) -> str:
    """Visible transcript wording for public control actions, not wire names."""
    return {
        "request_hint": "给我一点提示",
        "request_explanation": "讲解这个知识点",
        "request_example": "给我一个类似例子",
        "request_solution": "查看完整答案",
        "request_practice": "我想独立练一道",
        "request_foundation": "先补基础",
        "request_review": "做一道复习题",
        "accept_practice_offer": "接受练习",
        "decline_practice_offer": "暂不练习",
        "resume_problem": "回到原题",
        "end_problem": "结束本题",
        "start_diagnostic": "了解当前基础",
        "skip_diagnostic": "跳过诊断，继续辅导",
        "cancel_turn": "停止生成",
    }.get(command, "继续")


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
    if compact.startswith(("未知命令", "内部错误", "forbidden envelope", "unknown envelope")):
        return "这次操作没有处理成功，请重新同步对话后再试。"
    if not compact or _STATE_REJECT.search(compact) or _INTERNAL_LEAK.search(compact):
        return STUDENT_TRANSITION_FAILURE
    return compact


__all__ = [
    "project_assistant_message",
    "project_turn_error",
    "command_message_label",
    "STUDENT_TRANSITION_FAILURE",
]

"""Intent boundary for free-form Tutor input.

Parser is a tool of the math workflow, not the gate for every chat message.
Classification is structural (operators, task verbs, continuation cues) —
it does not special-case individual greetings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from mathtutor.application.input_normalizer import (
    normalize_input,
    normalize_math_problem_text,
)
from mathtutor.application.state_machine import CycleState


class ConversationMode(StrEnum):
    GENERAL_CHAT = "general_chat"
    MATH_PROBLEM = "math_problem"


class ConversationIntent(StrEnum):
    GENERAL_CHAT = "general_chat"
    MATH_PROBLEM = "math_problem"
    PROBLEM_CONTINUATION = "problem_continuation"


@dataclass(frozen=True, slots=True)
class RoutedIntent:
    intent: ConversationIntent
    mode: ConversationMode


_IDENT_HYPHEN = re.compile(r"(?<=[A-Za-z0-9])[-_](?=[A-Za-z0-9])")
_MATH_OPERATORS = re.compile(r"[+\-*/^=<>√∫∑∞]")
_EQUATION = re.compile(r"[^\s=]=[^\s=]")
_MATH_TASK_WORDS = re.compile(
    r"(?:计算|求解|解方程|化简|因式分解|求根(?!号)|求值|求极限|证明|解不等式|展开|根号)"
)
_LATEX_COMMAND = re.compile(
    r"\\(frac|sqrt|lim|sin|cos|tan|log|ln|sum|int|times|div|cdot|infty)\b"
)
_KNOWLEDGE_QUESTION = re.compile(
    r"(?:是什么|什么是|什么意思|怎么用|如何配置|哪款模型|哪个模型)"
)
_CONTINUATION_CUES = re.compile(
    r"(?:我不知道|我没懂|没看懂|看不懂|我不会|不太懂|为什么|再解释|"
    r"简单解释|再简单|提示一下|然后呢|下一步|这道题|这题|刚才那)"
)
_LATEX_MATH = re.compile(r"(\$[^$]+\$)|(\\\(.+?\\\))|(\\\[[\s\S]+?\\\])")


def _operator_surface(text: str) -> str:
    """Hyphens inside identifiers are not subtraction."""
    return _IDENT_HYPHEN.sub("", text)


def _looks_like_math_problem(text: str) -> bool:
    compact = " ".join(str(text or "").strip().split())
    if not compact:
        return False
    normalized = normalize_input(compact)
    surface = _operator_surface(normalized.normalized)
    blob = f"{compact} {normalized.normalized}"
    if _MATH_TASK_WORDS.search(blob) or _LATEX_MATH.search(blob) or _LATEX_COMMAND.search(blob):
        return True
    if _EQUATION.search(surface):
        return True
    if _MATH_OPERATORS.search(surface) and re.search(r"\d|[A-Za-z]", surface):
        return True
    if re.search(r"[a-zA-Z]\s*[+\-*/^=]", surface):
        return True
    return False


def _looks_like_knowledge_question(text: str) -> bool:
    compact = " ".join(str(text or "").strip().split())
    if not _KNOWLEDGE_QUESTION.search(compact):
        return False
    if _looks_like_math_problem(compact):
        return False
    return True


def _looks_like_continuation(text: str) -> bool:
    compact = " ".join(str(text or "").strip().split())
    if not compact or _looks_like_math_problem(compact):
        return False
    return bool(_CONTINUATION_CUES.search(compact))


def has_active_problem(state: CycleState | str | None) -> bool:
    if state is None or state == "":
        return False
    value = CycleState(state) if not isinstance(state, CycleState) else state
    return value not in {
        CycleState.PROBLEM_RECEIVED,
        CycleState.CLOSED,
        CycleState.UNSUPPORTED,
        CycleState.UNVERIFIED_BLOCKED,
    }


def classify_user_message(
    text: str,
    *,
    cycle_state: CycleState | str | None = None,
) -> RoutedIntent:
    """Route one user utterance given the current cycle, if any."""
    compact = " ".join(str(text or "").strip().split())
    active = has_active_problem(cycle_state)
    if _looks_like_math_problem(compact):
        return RoutedIntent(ConversationIntent.MATH_PROBLEM, ConversationMode.MATH_PROBLEM)
    if active and _looks_like_continuation(compact):
        return RoutedIntent(
            ConversationIntent.PROBLEM_CONTINUATION, ConversationMode.MATH_PROBLEM
        )
    return RoutedIntent(ConversationIntent.GENERAL_CHAT, ConversationMode.GENERAL_CHAT)


def is_concrete_math_input(text: str) -> bool:
    """Whether a message should enter the math constraint pipeline."""
    return classify_user_message(text).intent is ConversationIntent.MATH_PROBLEM


def fallback_tutor_reply(text: str) -> str:
    compact = text.strip()
    if not compact:
        return "我在。你可以问一个概念，或发来具体题目。"
    if _looks_like_math_problem(compact):
        return (
            "这个问题可以按数学概念来讨论。结构化求解器没有把它编成标准计算题，"
            "但不影响我们直接讲：你也可以继续补充你的想法。"
        )
    if _looks_like_knowledge_question(compact):
        return "这是一个概念问题。配好模型服务后我可以直接解释；现在也可以把它当作普通问题继续问。"
    return "我在。你可以继续描述想理解的概念，或发来具体题目。"


__all__ = [
    "ConversationIntent",
    "ConversationMode",
    "RoutedIntent",
    "classify_user_message",
    "fallback_tutor_reply",
    "has_active_problem",
    "is_concrete_math_input",
    "normalize_math_problem_text",
]

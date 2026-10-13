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
    ATTEMPT = "attempt"
    TEACHING_REQUEST = "teaching_request"
    CLARIFY_INTENT = "clarify_intent"


@dataclass(frozen=True, slots=True)
class RoutedIntent:
    intent: ConversationIntent
    mode: ConversationMode
    answer_text: str = ""
    command: str = ""
    problem_text: str = ""


_NEW_PROBLEM = re.compile(r"^(?:先不做这题[，,：: ]*|换(?:一道)?题[，,：: ]*|新题[，,：: ]*|解另一题[，,：: ]*)(?:解\s*)?(.+)$")
_ATTEMPT_PREFIX = re.compile(r"^(?:我的(?:答案|步骤)(?:是)?|我(?:算得|算出|得到|认为)|答案(?:是|为)|(?:移项|化简|计算)后(?:是|得到)?|下一步(?:是)?)[：:\s]*")
_NEGATED_ANSWER = re.compile(r"(?:不要|别|先不|不想|不用|不能)[^，,。；;]{0,18}(?:答案|解答)")
_ANSWER_REQUEST = re.compile(r"(?:给我|告诉我|查看|看|要|求|直接)[^，,。；;]{0,12}(?:答案|完整解答|完整解析)")
_HINT_REQUEST = re.compile(r"(?:提示|引导|一点帮助)")
_EXAMPLE_REQUEST = re.compile(r"(?:例子|例题|示例)")
_EXPLANATION_REQUEST = re.compile(r"(?:解释|讲解|讲一下|讲讲|为什么|是不是先|是否先|能不能先)")


def _requested_action(text: str) -> str:
    # Negation scopes to an answer request, not to the whole utterance.
    if _ANSWER_REQUEST.search(text) and not _NEGATED_ANSWER.search(text):
        return "request_solution"
    if _HINT_REQUEST.search(text):
        return "request_hint"
    if _EXAMPLE_REQUEST.search(text):
        return "request_example"
    if _EXPLANATION_REQUEST.search(text):
        return "request_explanation"
    from mathtutor.application.teaching_intent import rule_teaching_intent
    perception = rule_teaching_intent(text, context={})
    if perception.intent in {"explanation", "confusion"} and perception.confusion != "none":
        return "request_explanation"
    if _NEGATED_ANSWER.search(text):
        return "request_hint"
    return ""


def _math_fragment(text: str) -> tuple[str, bool]:
    # Split only at a following teaching request. Commas can belong to an
    # answer (for example a root set); never silently discard that content.
    first = text.strip()
    for boundary in re.finditer(r"[，,。；;]", text):
        following_clause = re.split(r"[，,。；;]", text[boundary.end():], maxsplit=1)[0]
        if _requested_action(following_clause):
            first = text[:boundary.start()].strip()
            break
    explicit = bool(_ATTEMPT_PREFIX.match(first))
    return _ATTEMPT_PREFIX.sub("", first).strip().rstrip("。"), explicit


def _is_answer_shape(text: str, variable: str | None, variables=()) -> bool:
    # This recognizes a candidate, never its correctness. Wrong answers have
    # exactly the same routing rights as correct ones. Verification happens later.
    from mathtutor.solving.parser import parse_problem
    from mathtutor.solving import nodes as n
    from mathtutor.learning.attempt_parser import EMPTY_ROOT_SET_TOKENS
    if text.lower() in EMPTY_ROOT_SET_TOKENS:
        return True
    if not re.fullmatch(r"[\s\dA-Za-z.,，;；+\-*/^=(){}\[\]\\$√]+", text):
        return False
    parsed = parse_problem(text)
    if parsed.kind != "parsed" or parsed.problem is None:
        return False
    ast = parsed.problem.ast
    if isinstance(ast, n.LinearSystem):
        equations = parsed.problem.normalized_ast.get("equations", [])
        return bool(variables) and all(any(side.get("kind") == "var" and side.get("name") in variables and not _variables(other)
            for side, other in ((eq.get("lhs", {}), eq.get("rhs", {})), (eq.get("rhs", {}), eq.get("lhs", {})))) for eq in equations)
    if parsed.problem.problem_type == "linear_inequality":
        return bool(variable) and parsed.problem.variable == variable
    if not isinstance(ast, n.Equation):
        return not parsed.problem.variable or parsed.problem.variable == variable
    # x=value / value=x is an answer; other equations need a step/new-topic
    # clarification unless explicitly introduced as a student step.
    data = parsed.problem.normalized_ast
    for side, other in ((data.get("lhs", {}), data.get("rhs", {})), (data.get("rhs", {}), data.get("lhs", {}))):
        if side.get("kind") == "var" and side.get("name") in {*variables, variable} and not _variables(other):
            return True
    return False


def _variables(ast) -> set[str]:
    if isinstance(ast, dict):
        own = {str(ast["name"])} if ast.get("kind") == "var" else set()
        return own.union(*(_variables(v) for v in ast.values()))
    if isinstance(ast, list):
        return set().union(*(_variables(v) for v in ast))
    return set()


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
_TOPIC_QUESTION = re.compile(r"(?:什么|怎样|怎么|如何|能否|可以|是否|能不能|吗|呢|区别|联系|规律|条件|成立|意义|适用|用法|理解|关于)")
_LATEX_MATH = re.compile(r"(\$[^$]+\$)|(\\\(.+?\\\))|(\\\[[\s\S]+?\\\])")


def _operator_surface(text: str) -> str:
    """Hyphens inside identifiers are not subtraction."""
    return _IDENT_HYPHEN.sub("", text)


def _looks_like_math_problem(text: str) -> bool:
    source = str(text or "").strip()
    if source.count("=") >= 2:
        source = re.sub(r"\s*\n\s*", ";", source)
    compact = " ".join(source.split())
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
        CycleState.GROUNDING,
        CycleState.AWAITING_CLARIFICATION,
        CycleState.SOLUTION_VERIFYING,
        CycleState.CLOSED,
        CycleState.UNSUPPORTED,
        CycleState.UNVERIFIED_BLOCKED,
    }


def classify_user_message(
    text: str,
    *,
    cycle_state: CycleState | str | None = None,
    variable: str | None = "x",
    skill_id: str = "",
    pending_math_text: str = "",
    variables: tuple[str, ...] = (),
    related_to_active: bool = False,
) -> RoutedIntent:
    """Route one user utterance given the current cycle, if any."""
    compact = " ".join(str(text or "").strip().split())
    active = has_active_problem(cycle_state)
    replacement = _NEW_PROBLEM.match(compact)
    if replacement:
        return RoutedIntent(ConversationIntent.MATH_PROBLEM, ConversationMode.MATH_PROBLEM, problem_text=replacement[1])
    if active and pending_math_text:
        if re.fullmatch(r"(?:这是|是)?(?:我的)?(?:步骤|下一步|推导)[。！!]?", compact):
            return RoutedIntent(ConversationIntent.ATTEMPT, ConversationMode.MATH_PROBLEM, answer_text=pending_math_text)
        if re.fullmatch(r"(?:这是|是)?(?:一道)?新题[。！!]?", compact):
            return RoutedIntent(ConversationIntent.MATH_PROBLEM, ConversationMode.MATH_PROBLEM, problem_text=pending_math_text)
    action = _requested_action(compact)
    fragment, explicit_attempt = _math_fragment(compact)
    if active and (explicit_attempt or _is_answer_shape(fragment, variable, variables)):
        return RoutedIntent(ConversationIntent.ATTEMPT, ConversationMode.MATH_PROBLEM, answer_text=fragment, command=action)
    from mathtutor.learning.skills import relates_to_skill
    if active and not explicit_attempt and (related_to_active or relates_to_skill(compact, skill_id)) and (
        _TOPIC_QUESTION.search(compact) or not _looks_like_math_problem(compact)
    ):
        return RoutedIntent(ConversationIntent.TEACHING_REQUEST, ConversationMode.MATH_PROBLEM,
                            command=action or "request_explanation")
    if action and (active or action != "request_explanation"):
        return RoutedIntent(ConversationIntent.TEACHING_REQUEST, ConversationMode.MATH_PROBLEM, command=action)
    # An unbound explanation can be a self-contained concept question. Keep
    # the existing math/ordinary-chat pipeline instead of requiring a cycle.
    if active and _looks_like_math_problem(compact):
        return RoutedIntent(ConversationIntent.CLARIFY_INTENT, ConversationMode.MATH_PROBLEM)
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

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
from mathtutor.application.math_operation_scope import requires_unstructured_math


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
def _requested_action(text: str) -> str:
    # Routing and the semantic adapter must agree about consent to reveal an
    # answer, including when the message contains an old dialogue or English.
    from mathtutor.application.teaching_intent import rule_teaching_intent
    perception = rule_teaching_intent(text, context={})
    return {"solution": "request_solution", "hint": "request_hint", "example": "request_example",
            "explanation": "request_explanation", "practice": "request_practice"}.get(perception.intent, "")


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
    from mathtutor.solving.quadratic_inequality import parse_answer
    if variable and re.search(r"[<>≤≥≠]|全体实数|任意实数|一切实数", text) and parse_answer(text, variable) is not None:
        return True  # a solution set such as x>2, x<2或x>3, 2<x<3
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


_IDENT_HYPHEN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]{2,}[A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+(?![A-Za-z0-9_])")
_MATH_OPERATORS = re.compile(r"[+\-*/^=<>≤≥≠√∫∑∞]")
_EQUATION = re.compile(r"[^\s=]=[^\s=]")
_MATH_TASK_WORDS = re.compile(
    r"(?:计算|求解|解方程|化简|因式分解|求根(?!号)|求值|求极限|证明|解不等式|展开|根号|"
    r"(?:求|算).{0,20}(?:面积|体积|周长|概率|长度|角度)|(?:猜|估计).{0,12}[xyz].{0,8}(?:多少|等于)|"
    r"[xyz]\s*(?:的值|等于|是).{0,4}多少|求\s*[xyz](?:的值)?(?:[。?？]|$)|"
    r"(?:面积|体积|周长|长度|角度)(?:是|为)?多少)"
)
_OPEN_MATH = re.compile(r"什么是|是什么|是什么意思|为什么|为何|解释|讲解|如何理解|怎么理解|有什么用|区别|联系|"
                        r"\b(?:what is|what are|why|explain|how to understand|difference between)\b", re.I)
_EXPLICIT_COMPUTATION = re.compile(r"计算|求解|求值|解方程|解不等式|求(?:面积|体积|导数|极限)|"
                                   r"\b(?:solve|calculate|compute|evaluate|prove)\b", re.I)
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
_UNBOUND_TASK_REFERENCE = re.compile(r"^(?:把|请|帮我|麻烦|再|给我|\s)*(?:这|那|刚才那|上一|前一)(?:道)?题(?:目)?(?:帮我)?(?:算|解|做|计算|求解)(?:一下|一遍|出来|了|[。！？?\s])*$")


def _operator_surface(text: str) -> str:
    """Hyphens inside identifiers are not subtraction."""
    return _IDENT_HYPHEN.sub(lambda m: m.group().replace("-", "").replace("_", ""), text)


def _command_quotation(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and all(re.fullmatch(r">\s*/[A-Za-z][A-Za-z0-9_-]*(?:\s.*)?", line) for line in lines)


def is_open_math_question(text: str) -> bool:
    if (requires_unstructured_math(text) and re.search(r"提示|\bhint\b", text, re.I)
            and _requested_action(text) in {"request_hint", "request_explanation", "request_example"}):
        return True
    if re.search(r"为什么|为何|\bwhy\b", text, re.I) and not re.search(
            r"求解|解方程|解不等式|求(?:值|面积|体积|导数|极限)|\b(?:solve|evaluate|prove)\b", text, re.I):
        return True
    return bool(_OPEN_MATH.search(text) and not _EXPLICIT_COMPUTATION.search(text))


def _looks_like_math_problem(text: str) -> bool:
    source = str(text or "").strip()
    if source.count("=") >= 2:
        source = re.sub(r"\s*\n\s*", ";", source)
    compact = " ".join(source.split())
    if not compact:
        return False
    if is_open_math_question(source):
        return False
    if requires_unstructured_math(source):
        return True
    normalized = normalize_input(compact)
    surface = _operator_surface(normalized.normalized or source)
    blob = f"{compact} {normalized.normalized}"
    if (_MATH_TASK_WORDS.search(compact) or _MATH_TASK_WORDS.search(normalized.normalized)
            or _LATEX_MATH.search(blob) or _LATEX_COMMAND.search(blob)):
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
    if _command_quotation(str(text or "")):
        return RoutedIntent(ConversationIntent.GENERAL_CHAT, ConversationMode.GENERAL_CHAT)
    active = has_active_problem(cycle_state)
    if _UNBOUND_TASK_REFERENCE.fullmatch(compact):
        return RoutedIntent(ConversationIntent.PROBLEM_CONTINUATION if active else ConversationIntent.MATH_PROBLEM,
                            ConversationMode.MATH_PROBLEM)
    replacement = _NEW_PROBLEM.match(compact)
    if replacement:
        return RoutedIntent(ConversationIntent.MATH_PROBLEM, ConversationMode.MATH_PROBLEM, problem_text=replacement[1])
    if active and pending_math_text:
        if re.fullmatch(r"(?:这是|是)?(?:我的)?(?:步骤|下一步|推导)[。！!]?", compact):
            return RoutedIntent(ConversationIntent.ATTEMPT, ConversationMode.MATH_PROBLEM, answer_text=pending_math_text)
        if re.fullmatch(r"(?:这是|是)?(?:一道)?新题[。！!]?", compact):
            return RoutedIntent(ConversationIntent.MATH_PROBLEM, ConversationMode.MATH_PROBLEM, problem_text=pending_math_text)
    if requires_unstructured_math(str(text or "")) and not is_open_math_question(str(text or "")):
        # A derivative/extremum question cannot be submitted as an algebra
        # attempt or a simplification of the contained polynomial.  The
        # constraint layer preserves its original operation for free teaching.
        return RoutedIntent(ConversationIntent.MATH_PROBLEM, ConversationMode.MATH_PROBLEM)
    action = _requested_action(str(text or ""))
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
    if _command_quotation(compact):
        return "这是一段引用的命令，没有执行。可以继续讨论它的含义。"
    if not compact:
        return "我在。你可以问一个概念，或发来具体题目。"
    from mathtutor.application.offline_foundations import offline_concept_reply
    local = offline_concept_reply(compact)
    if local:
        return local.text
    if _looks_like_math_problem(compact) or is_open_math_question(compact) or _looks_like_knowledge_question(compact):
        if not re.search(r"[\u4e00-\u9fff]", compact):
            return ("I don't have a model explanation for this question. Offline, I can check supported arithmetic, "
                    "equations and inequalities, and simple polynomial derivatives. Configure a model in Settings "
                    "for a broader explanation, or send a basic exercise.")
        return (
            "当前没有可用的模型讲解，内置概念资料也没有覆盖这个问题。"
            "离线可以核验受支持的算术、方程、不等式和简单多项式导数，"
            "也能说明分数运算、分配律、同类项和移项的基础规则。"
            "可以在设置中配置模型继续讨论，或直接发一道基础练习。"
        )
    return "我在。你可以继续描述想理解的概念，或发来具体题目。"


__all__ = [
    "ConversationIntent",
    "ConversationMode",
    "RoutedIntent",
    "classify_user_message",
    "fallback_tutor_reply",
    "has_active_problem",
    "is_concrete_math_input",
    "is_open_math_question",
    "normalize_math_problem_text",
]

"""Read-only language interpretation; never mathematical or permission authority."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SemanticIntentPayload(BaseModel):
    """The only fields a language model may propose."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    intent: Literal["explanation", "hint", "example", "solution", "practice", "followup", "confusion", "self_report", "general_chat", "ambiguous"]
    confusion: Literal["none", "mild", "explicit", "persistent"]
    resolved: bool
    scope: Literal["current_goal", "current_problem", "same_skill", "other", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    evidence_quote: str = Field(max_length=512)
    target_subgoal_id: str = Field(max_length=128)


class SemanticTeachingIntent(SemanticIntentPayload):
    """Source and fallback metadata are assigned by the server, not the LLM."""

    source: Literal["llm", "rules", "rules_budget"] = "rules"
    fallback_reason: str = ""


_QUOTED = re.compile(r'“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"[^"\n]*"|(?<!\w)\x27[^\x27\n]*\x27(?!\w)')
_META = re.compile(r"(?:不懂|没懂|听不懂|困惑|糊涂)(?:这(?:句|个)?(?:话|词|表达))?(?:是|的)?什么意思")
_NEGATED_CONFUSION = re.compile(r"(?:不是|并非|没有|并不|不再)[^，,。；;]{0,8}(?:不懂|没懂|听不懂|困惑|糊涂|模糊)")
_RESOLVED = re.compile(r"(?:我)?(?:已经|终于|现在|这次)?(?:懂了|明白了|理解了|清楚了|会了)")
_CONFUSION = re.compile(r"(?:不太懂|没(?:有)?(?:听|看|弄)?懂|听不懂|看不懂|没(?:有)?(?:弄)?明白|没(?:有)?理解|不明白|不理解|不懂|不是(?:已经)?(?:懂了|明白了|理解了)|糊涂|模糊|没(?:有)?接上|没(?:有)?跟上|跟不上|困惑|卡住|换(?:个|一种)?角度)")
_PERSISTENT = re.compile(r"(?:还是|仍然|依然|又|一直|仍旧)")
_NEGATED_ANSWER = re.compile(r"(?:不要|别|先不|不想|不用|不能|不需要)[^，,。；;]{0,18}(?:答案|解答|解法|解析|结果|算出来|解完|做完)")
_EXPLICIT_SOLUTION = re.compile(
    r"(?:给我|告诉我|请(?:给|展示|提供)|我(?:想要|需要|想|要)(?:看|知道|查看)?|查看|看一下|让我看|直接给|显示|展示)[^，,。；;]{0,12}(?:答案|完整解答|完整解析|完整解法)"
    r"|(?:请|帮我|麻烦)(?:完整地?|详细地?)?(?:求解|解答|解出|解一下|做一下)(?:这|该|此)?(?:道|个)?(?:题|问题|方程)"
    r"|(?:请|帮我|麻烦)(?:给出|提供)?完整(?:地)?(?:解答|解析|求解|解法)"
)

_EN_NEGATED_ANSWER = re.compile(
    r"\b(?:do\s+not|don't|dont|don’t|never|avoid)\s+(?:(?:directly|fully|completely)\s+)?"
    r"(?:(?:give|reveal|show|tell|state|write|provide|want|need|share|include|print|say)\b[^.!?;\n]{0,60}?\b(?:answer|solution)\b"
    r"|(?:solve|solving|finish|answer|answering)\b|(?:the\s+|a\s+)?(?:final\s+|full\s+)?solution\b)"
    r"|\bwithout\s+(?:(?:a|the|any|full|complete|final)\s+)*(?:answer|solution|solving)\b"
    r"|\bwithout\s+(?:giving|revealing|showing|stating|providing|sharing)\b[^.!?;\n]{0,60}?\b(?:answer|solution)\b",
    re.I,
)
_EN_EXPLICIT_SOLUTION = re.compile(
    r"\b(?:provide|give|show|state|write|tell\s+me)\s+(?:me\s+)?(?:your\s+|the\s+|a\s+)?(?:final\s+answer|complete\s+(?:correct\s+)?solution|full\s+(?:solution|answer)|answer|solution)\b"
    r"|(?:^|[.!?\n:;]\s*|\b(?:please|can\s+you|could\s+you|would\s+you|will\s+you)\s+)solve\s+"
    r"(?:it|this|the\s+(?:question|problem|equation)|this\s+(?:question|problem|equation))\b", re.I)
_HINT_ONLY = re.compile(
    r"(?:只|仅)(?:需要|要|用|给|讲|提供)?(?:我)?(?:一个|一点|一些|条)?(?:小)?(?:提示|引导|思路)"
    r"|(?:提示|引导)(?:就好|即可|就行)"
    r"|\b(?:only|just)\s+(?:(?:give|show|provide|offer)\s+(?:me\s+)?)?(?:(?:a|one|some)\s+)?(?:hints?|guidance|nudge|clue|next\s+step)\b"
    r"|\b(?:give|show|provide|offer)\s+(?:me\s+)?(?:only|just)\s+(?:(?:a|one|some)\s+)?(?:hints?|guidance|nudge|clue|next\s+step)\b",
    re.I,
)
_HINT_REQUEST = re.compile(r"(?:提示|引导|一点帮助)|\b(?:hints?|nudge|clue)\b", re.I)
_EXAMPLE_REQUEST = re.compile(r"(?:例子|例题|示例)|\b(?:an?\s+|another\s+|worked\s+)example\b", re.I)
_PRACTICE_REQUEST = re.compile(r"(?:练习|出道题|来一道|换一道)|\b(?:practice|another\s+(?:question|problem))\b", re.I)
_EXPLANATION_REQUEST = re.compile(
    r"(?:解释|讲解|讲一下|讲讲|为什么|什么意思|换.*角度|是不是先|是否先|能不能先)"
    r"|\b(?:explain|why|what\s+does|how\s+(?:does|did|can|do)|don't\s+understand|do\s+not\s+understand|confused)\b", re.I)
_LATEST_MESSAGE = re.compile(r"(?:^|\n)\s*(?:student[’']s\s+latest\s+message|学生(?:的)?最新(?:消息|问题))\s*[:：]", re.I)
_HISTORY = re.compile(r"(?:^|\n)\s*(?:conversation|dialog(?:ue)?\s+history|对话(?:记录|历史)?)\s*[:：]", re.I)
_PROBLEM_HEADING = re.compile(r"(?:^|\n)\s*(?:problem|question|题目|原题)\s*[:：]", re.I)


def current_request_text(text: str) -> str:
    """Disclosure is governed by the current request, not an embedded transcript."""
    source = str(text or "")
    latest = list(_LATEST_MESSAGE.finditer(source))
    if latest:
        source = source[latest[-1].end():]
    history = _HISTORY.search(source)
    return source[:history.start()] if history else source


def _request_constraints_text(text: str) -> str:
    """Keep outer response limits, without treating old/problem text as consent.

    A request can wrap a problem and the latest student message. Its instruction
    to give only a hint still applies, while a command inside the old problem or
    conversation cannot authorize revealing the solution to the current student.
    """
    source = str(text or "")
    latest = list(_LATEST_MESSAGE.finditer(source))
    if not latest:
        return current_request_text(source)
    boundaries = [latest[0].start()]
    boundaries.extend(match.start() for pattern in (_HISTORY, _PROBLEM_HEADING)
                      if (match := pattern.search(source)) is not None)
    return source[:min(boundaries)] + "\n" + current_request_text(source)


def contains_student_work(text: str) -> bool:
    return bool(re.search(r"(?:^|\n)\s*(?:student(?:[’']s)?\s*(?:solution|latest\s+message)?|learner|teacher|tutor|conversation|previous\s+explanation|学生(?:解答|步骤|最新消息)?|老师|教师|对话记录)\s*[:：]", text, re.I))


def current_subgoal_id(context: dict) -> str:
    current = context.get("current_subgoal")
    if isinstance(current, dict) and current.get("id"):
        return str(current["id"])
    if context.get("target_subgoal_id"):
        return str(context["target_subgoal_id"])
    goals = context.get("subgoals") or ()
    index = context.get("current_subgoal_index", 0)
    if isinstance(index, int) and 0 <= index < len(goals) and isinstance(goals[index], dict):
        return str(goals[index].get("id") or "")
    return ""


def visible_self_report(text: str) -> str:
    """Quoted words and metalinguistic questions are not student state facts."""
    unquoted = _QUOTED.sub(" ", text)
    if _META.search(unquoted):
        return ""
    current = re.search(r"(?:[，,。；;]|但是|不过|但)\s*(?:我)?(?:现在|后来|已经|这次|终于)[^，,。；;]*$", unquoted)
    if current and _RESOLVED.search(current.group()):
        # Past confusion is not current state once the student explicitly
        # reports a later resolution. A new unresolved clause still wins.
        unquoted = current.group()
    return _NEGATED_CONFUSION.sub(" ", unquoted)


def negates_solution(text: str) -> bool:
    unquoted = _QUOTED.sub(" ", _request_constraints_text(text))
    for match in _NEGATED_ANSWER.finditer(unquoted):
        if not re.match(r"(?:不要|别|先不|不想|不用|不能|不需要)(?:使用|用|通过|采用)", match.group()):
            return True
    for match in _EN_NEGATED_ANSWER.finditer(unquoted):
        # Banning a method does not ban an answer.  In particular, "do not
        # solve it using calculus" still requests the solution by another
        # method; "do not solve it for me" still limits disclosure.
        if re.match(r"(?:do\s+not|don't|dont|don’t|never|without|avoid)\s+(?:use|using|apply|applying)\b", match.group(), re.I):
            continue
        if (re.search(r"\b(?:solve|solving)\b$", match.group(), re.I)
                and re.match(r"(?:\s+(?:it|this|that|(?:the|this)\s+(?:problem|equation|question)))?\s+(?:using|with|by|via)\b",
                             unquoted[match.end():], re.I)):
            continue
        return True
    return bool(_HINT_ONLY.search(unquoted))


def explicit_solution_request(text: str) -> bool:
    """Disclosure safety gate: mentioning an answer is not asking to reveal it."""
    unquoted = _QUOTED.sub(" ", current_request_text(text))
    chinese_request = any(not re.match(r"\s*(?:为什么|为何|怎么|是怎么|如何)", unquoted[match.end():])
                          for match in _EXPLICIT_SOLUTION.finditer(unquoted))
    return bool(chinese_request or _EN_EXPLICIT_SOLUTION.search(unquoted)) and not negates_solution(text)


def response_scope_instruction(text: str) -> str:
    """A delivery constraint, not mathematical validation or permission.

    This applies equally to ordinary chat and solver-backed teaching. It does
    not invent a mandatory quiz after a complete answer or turn a request for a
    reason into an invitation to reveal every later step.
    """
    current = _QUOTED.sub(" ", current_request_text(text))
    if negates_solution(text):
        return ("本轮学生要求限制答案披露：若问原因，直接解释所问原因；若要提示，给一个具体可执行的小步。"
                "不要算出或揭示最终答案，不把完整解法藏在提示、示例、总结或反问中。")
    if explicit_solution_request(text):
        return ("本轮学生明确要求解答：给出覆盖所问内容的完整推导及最终答案，保留必要条件与检验。"
                "不要用反问、练习或强制等待学生先尝试来替代已请求的解答。")
    if _HINT_REQUEST.search(current):
        return "本轮学生要提示：给一个具体可执行的小步及必要的理由，停在该步，不提前完成后续解答。"
    if _EXPLANATION_REQUEST.search(current):
        return ("本轮先直接回答学生所问的原因、概念或具体步骤，再按需要给一个小步。"
                "不要只反问，也不要从头展开学生没有要求的完整解答。")
    return ""


def rule_teaching_intent(text: str, *, context: dict) -> SemanticTeachingIntent:
    """Conservative offline fallback; reports language, never student mastery."""
    raw = str(text or "").strip()
    current = current_request_text(raw)
    unquoted = _QUOTED.sub(" ", current)
    speech = visible_self_report(current)
    difficulty = _CONFUSION.search(speech)
    resolved = bool(_RESOLVED.search(speech)) and not difficulty
    target = current_subgoal_id(context)
    active = bool(target or context.get("problem_id") or context.get("display_text") or context.get("problem_text"))
    scope = "current_goal" if target else "current_problem" if active else "uncertain"
    confusion = ("persistent" if _PERSISTENT.search(speech) else "mild" if "不太" in speech or "换" in speech else "explicit") if difficulty else "none"
    if explicit_solution_request(raw):
        intent = "solution"
    elif _EXAMPLE_REQUEST.search(unquoted):
        intent = "example"
    elif _PRACTICE_REQUEST.search(unquoted):
        intent = "practice"
    elif _HINT_REQUEST.search(unquoted):
        intent = "hint"
    elif difficulty:
        intent = "explanation"
    elif resolved or _NEGATED_CONFUSION.search(unquoted):
        intent = "self_report"
    elif _EXPLANATION_REQUEST.search(unquoted):
        intent = "explanation"
    elif negates_solution(raw):
        intent = "hint"
    elif active and re.search(r"(?:然后呢|下一步|刚才|这个|这一步|继续)", unquoted):
        intent = "followup"
    else:
        intent = "general_chat" if raw else "ambiguous"
    if _META.search(unquoted) or (_QUOTED.search(raw) and not difficulty and re.search(r"(?:什么意思|这句话|这个词)", unquoted)):
        scope, target = "other", ""
    return SemanticTeachingIntent(intent=intent, confusion=confusion, resolved=resolved,
        scope=scope, confidence=0.9 if intent not in {"general_chat", "ambiguous"} else 0.5,
        evidence_quote=raw[:512], target_subgoal_id=target, source="rules")


__all__ = ["SemanticTeachingIntent", "SemanticIntentPayload", "rule_teaching_intent", "current_subgoal_id", "visible_self_report", "negates_solution", "explicit_solution_request", "current_request_text", "contains_student_work", "response_scope_instruction"]

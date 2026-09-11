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


_QUOTED = re.compile(r'“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"[^"\n]*"|\x27[^\x27\n]*\x27')
_META = re.compile(r"(?:不懂|没懂|听不懂|困惑|糊涂)(?:这(?:句|个)?(?:话|词|表达))?(?:是|的)?什么意思")
_NEGATED_CONFUSION = re.compile(r"(?:不是|并非|没有|并不|不再)[^，,。；;]{0,8}(?:不懂|没懂|听不懂|困惑|糊涂|模糊)")
_RESOLVED = re.compile(r"(?:我)?(?:已经|终于|现在|这次)?(?:懂了|明白了|理解了|清楚了|会了)")
_CONFUSION = re.compile(r"(?:不太懂|没(?:有)?(?:听|看|弄)?懂|听不懂|看不懂|没(?:有)?(?:弄)?明白|没(?:有)?理解|不明白|不理解|不懂|不是(?:已经)?(?:懂了|明白了|理解了)|糊涂|模糊|没(?:有)?接上|没(?:有)?跟上|跟不上|困惑|卡住|换(?:个|一种)?角度)")
_PERSISTENT = re.compile(r"(?:还是|仍然|依然|又|一直|仍旧)")
_NEGATED_ANSWER = re.compile(r"(?:不要|别|先不|不想|不用|不能|不需要)[^，,。；;]{0,18}(?:答案|解答|解法|解析)")
_EXPLICIT_SOLUTION = re.compile(r"(?:给我|告诉我|请(?:给|展示|提供)|我(?:想要|需要|想|要)(?:看|知道|查看)?|查看|看一下|让我看|直接给|显示|展示)[^，,。；;]{0,12}(?:答案|完整解答|完整解析|完整解法)")


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
    return bool(_NEGATED_ANSWER.search(_QUOTED.sub(" ", text)))


def explicit_solution_request(text: str) -> bool:
    """Disclosure safety gate: mentioning an answer is not asking to reveal it."""
    return bool(_EXPLICIT_SOLUTION.search(_QUOTED.sub(" ", text))) and not negates_solution(text)


def rule_teaching_intent(text: str, *, context: dict) -> SemanticTeachingIntent:
    """Conservative offline fallback; reports language, never student mastery."""
    raw = str(text or "").strip()
    unquoted = _QUOTED.sub(" ", raw)
    speech = visible_self_report(raw)
    difficulty = _CONFUSION.search(speech)
    resolved = bool(_RESOLVED.search(speech)) and not difficulty
    target = current_subgoal_id(context)
    active = bool(target or context.get("problem_id") or context.get("display_text") or context.get("problem_text"))
    scope = "current_goal" if target else "current_problem" if active else "uncertain"
    confusion = ("persistent" if _PERSISTENT.search(speech) else "mild" if "不太" in speech or "换" in speech else "explicit") if difficulty else "none"
    if re.search(r"(?:例子|例题|示例)", unquoted):
        intent = "example"
    elif re.search(r"(?:练习|出道题|来一道|换一道)", unquoted):
        intent = "practice"
    elif explicit_solution_request(raw):
        intent = "solution"
    elif re.search(r"(?:提示|引导|一点帮助)", unquoted):
        intent = "hint"
    elif difficulty:
        intent = "explanation"
    elif resolved or _NEGATED_CONFUSION.search(unquoted):
        intent = "self_report"
    elif re.search(r"(?:解释|讲解|讲一下|讲讲|为什么|什么意思|换.*角度)", unquoted):
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


__all__ = ["SemanticTeachingIntent", "SemanticIntentPayload", "rule_teaching_intent", "current_subgoal_id", "visible_self_report", "negates_solution", "explicit_solution_request"]

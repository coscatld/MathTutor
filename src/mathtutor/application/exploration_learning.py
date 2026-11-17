"""Source-independent inquiry paths from bounded, server-assessed observations."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Goal = Literal["understand", "apply", "compare"]
Language = Literal["zh", "en"]
Action = Literal[
    "read", "worked_example", "compare_methods", "independent_check",
    "clarify_conflict", "transfer_check", "review_prerequisite", "choose_goal",
]
POLICY = "exploration_learning_v1"
MAX_OBSERVATIONS = 256


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LearningObservation(_Model):
    """Internal event. HTTP clients must submit answers, never these grades."""

    event_id: str = Field(min_length=1, max_length=160)
    event_type: Literal["view", "bookmark", "self_report", "attempt", "answer_exposed"]
    concept_id: str = Field(min_length=1, max_length=100)
    actor: Literal["learner", "system"] = "learner"
    item_id: str | None = Field(default=None, max_length=160)
    attempt_id: str | None = Field(default=None, max_length=160)
    answer: str | None = Field(default=None, max_length=240)
    correct: bool | None = None
    verification: Literal["rule", "none"] = "none"
    assistance: Literal["none", "hint", "answer_seen"] = "none"
    occurred_at: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def aware_clock(self):
        if self.occurred_at and datetime.fromisoformat(self.occurred_at).tzinfo is None:
            raise ValueError("Observation time must include a timezone")
        return self


class ConceptNode(_Model):
    concept_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)


class Prerequisite(_Model):
    before: str
    after: str


class Curriculum(_Model):
    nodes: tuple[ConceptNode, ...] = Field(max_length=128)
    prerequisites: tuple[Prerequisite, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def valid_graph(self):
        ids = {node.concept_id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("Duplicate curriculum concept")
        parents: dict[str, set[str]] = {key: set() for key in ids}
        for edge in self.prerequisites:
            if edge.before not in ids or edge.after not in ids:
                raise ValueError("Unknown prerequisite concept")
            parents[edge.after].add(edge.before)
        visited: set[str] = set()
        active: set[str] = set()

        def visit(key: str):
            if key in active:
                raise ValueError("Cyclic prerequisites")
            if key in visited:
                return
            active.add(key)
            for parent in parents[key]:
                visit(parent)
            active.remove(key)
            visited.add(key)

        for key in ids:
            visit(key)
        return self


class CheckChoice(_Model):
    id: str
    text: str


class CheckPrompt(_Model):
    check_id: str
    concept_id: str
    prompt: str
    response_type: Literal["choice", "number"]
    choices: tuple[CheckChoice, ...] = ()
    purpose: Literal["boundary", "transfer"]


class CheckResult(_Model):
    correctness: Literal["correct", "incorrect", "unknown"]
    independent: bool
    feedback: str
    observation: LearningObservation


class LearningStep(_Model):
    step_id: str
    concept_id: str
    action: Action
    title: str
    reason: str
    basis_observation_ids: tuple[str, ...] = ()


class LearningPlan(_Model):
    policy: str = POLICY
    original_question: str
    goal: Goal
    target_concept: str
    concept_title: str
    evidence_state: Literal[
        "unknown", "assisted_only", "needs_check", "mixed_observations", "independent_observed",
    ]
    independent_successes: int
    basis_observation_ids: tuple[str, ...]
    steps: tuple[LearningStep, ...] = Field(max_length=3)
    check: CheckPrompt | None
    prerequisite_basis: Literal["authored_curriculum", "provided_curriculum", "none"]


@dataclass(frozen=True)
class _Check:
    check_id: str
    concept_id: str
    prompt: tuple[str, str]
    answer: str
    explanation: tuple[str, str]
    choices: tuple[tuple[str, str], ...] = ()
    purpose: Literal["boundary", "transfer"] = "boundary"


_TITLES = {
    "finite_decimal": ("有限小数", "Finite decimals"),
    "decimal_limit": ("无限小数与极限", "Repeating decimals and limits"),
    "signed_numbers": ("数的正负", "Signed numbers"),
    "square_root": ("根式与符号条件", "Square roots and sign conditions"),
    "equation_division": ("等式除法与丢解", "Division in equations"),
    "limit": ("左右极限", "One-sided limits"),
    "derivative": ("连续与可导", "Continuity and differentiability"),
    "geometric_series": ("等比级数的收敛条件", "Geometric-series convergence"),
    "probability": ("条件概率", "Conditional probability"),
    "linear_algebra": ("线性相关与基", "Linear dependence and bases"),
}
_ALIASES = {
    "decimal_limit": ("0.999", "无限小数", "循环小数", "repeating decimal", "decimal"),
    "square_root": ("sqrt", "根式", "平方根", "√", "square root"),
    "equation_division": ("丢解", "除以x", "除以 x", "x²=x", "x^2=x", "division", "方程"),
    "derivative": ("可导", "不可微", "导数", "derivative", "differentiab", "连续"),
    "geometric_series": ("等比", "级数", "geometric series", "converg", "series"),
    "probability": ("概率", "贝叶斯", "probability", "bayes", "假阳性"),
    "linear_algebra": ("线性", "向量", "矩阵", "linear", "vector", "basis"),
    "limit": ("极限", "limit"),
}
_EDGES = (
    ("finite_decimal", "decimal_limit"), ("signed_numbers", "square_root"),
    ("signed_numbers", "equation_division"), ("limit", "derivative"),
    ("limit", "geometric_series"),
)
_CHECKS = (
    _Check("decimal.finite", "decimal_limit",
        ("有限小数 0.999 与 1 的差是多少？", "What is 1 minus the finite decimal 0.999?"), "1/1000",
        ("1 − 0.999 = 0.001。有限截断与无限循环小数是不同对象。", "1 − 0.999 = 0.001. A finite truncation differs from an infinite repeating decimal.")),
    _Check("decimal.limit", "decimal_limit",
        ("实数序列 1 − 10⁻ⁿ 的极限是多少？", "What is the limit of the real sequence 1 − 10⁻ⁿ?"), "1",
        ("10⁻ⁿ 趋于 0，所以该序列趋于 1；每个有限项小于 1 不妨碍极限等于 1。", "10⁻ⁿ tends to 0, so the limit is 1, although every finite term is less than 1."), purpose="transfer"),
    _Check("decimal.repeat", "decimal_limit",
        ("在实数十进制定义下，0.333… × 3 等于多少？", "Under the usual real decimal definition, what is 0.333… × 3?"), "1",
        ("0.333… = 1/3，因此乘以 3 等于 1。", "0.333… = 1/3, so multiplying by 3 gives 1."), purpose="transfer"),
    _Check("root.negative", "square_root",
        ("当 x = −3 时，√(x²) 等于多少？", "For x = −3, what is √(x²)?"), "3",
        ("实数的算术平方根非负，√9 = 3；一般地 √(x²) = |x|。", "The principal square root is nonnegative: √9 = 3. In general, √(x²) = |x|.")),
    _Check("root.condition", "square_root",
        ("实数范围内，√(x²) = x 在什么条件下成立？", "For real x, when does √(x²) = x hold?"), "B",
        ("仅当 x ≥ 0 时 |x| = x。", "|x| equals x exactly when x ≥ 0."),
        (("所有实数", "All real numbers"), ("x ≥ 0", "x ≥ 0"), ("x < 0", "x < 0")), "transfer"),
    _Check("root.shift", "square_root",
        ("当 t = 1 时，√((t − 4)²) 等于多少？", "For t = 1, what is √((t − 4)²)?"), "3",
        ("t − 4 = −3，取算术平方根后得到 |−3| = 3。", "t − 4 = −3, and the principal square root gives |−3| = 3."), purpose="transfer"),
    _Check("division.zero", "equation_division",
        ("x² = x 的全部实数解是哪一组？", "Which set contains all real solutions of x² = x?"), "B",
        ("x(x − 1) = 0，解为 0 和 1；直接除以 x 会漏掉 0。", "x(x − 1) = 0 gives 0 and 1. Dividing by x would lose 0."),
        (("只有 1", "Only 1"), ("0 和 1", "0 and 1"), ("只有 0", "Only 0"))),
    _Check("division.shift", "equation_division",
        ("(x − 2)(x + 1) = 0 的全部解是哪一组？", "Which set contains all solutions of (x − 2)(x + 1) = 0?"), "C",
        ("两个因子分别为 0，得到 x = 2 或 x = −1。", "Setting each factor to zero gives x = 2 or x = −1."),
        (("只有 −1", "Only −1"), ("只有 2", "Only 2"), ("−1 和 2", "−1 and 2")), "transfer"),
    _Check("derivative.absolute", "derivative",
        ("f(x) = |x| 在 x = 0 处的情况是？", "What is true about f(x) = |x| at x = 0?"), "B",
        ("它在 0 连续，但左右差商极限分别为 −1 与 1，因此不可导。", "It is continuous at 0, but the one-sided difference quotients tend to −1 and 1, so it is not differentiable."),
        (("连续且可导", "Continuous and differentiable"), ("连续但不可导", "Continuous but not differentiable"), ("不连续", "Not continuous"))),
    _Check("derivative.square", "derivative",
        ("f(x) = x² 在 x = 0 处的导数是多少？", "What is the derivative of f(x) = x² at x = 0?"), "0",
        ("差商 h²/h = h（h ≠ 0），其极限为 0。", "The difference quotient is h²/h = h for h ≠ 0, whose limit is 0."), purpose="transfer"),
    _Check("series.half", "geometric_series",
        ("级数 1 + 1/2 + 1/4 + … 的和是多少？", "What is the sum of 1 + 1/2 + 1/4 + …?"), "2",
        ("公比 1/2 的绝对值小于 1，和为 1/(1 − 1/2) = 2。", "The ratio 1/2 has absolute value below 1, so the sum is 1/(1 − 1/2) = 2.")),
    _Check("series.boundary", "geometric_series",
        ("把公比 r = 2 代入 1/(1 − r)，能得到 1 + 2 + 4 + … 的收敛和吗？", "Does substituting r = 2 into 1/(1 − r) give the convergent sum of 1 + 2 + 4 + …?"), "B",
        ("不能。该公式作为无穷等比级数和要求 |r| < 1；r = 2 时级数发散。", "No. The infinite geometric-series formula requires |r| < 1; for r = 2 the series diverges."),
        (("能，和为 −1", "Yes, the sum is −1"), ("不能，级数发散", "No, the series diverges")), "transfer"),
    _Check("probability.conditional", "probability",
        ("P(A∩B)=0.2，P(B)=0.5。P(A|B) 等于多少？", "If P(A∩B)=0.2 and P(B)=0.5, what is P(A|B)?"), "2/5",
        ("P(B)>0 时，P(A|B)=P(A∩B)/P(B)=0.4。", "Since P(B)>0, P(A|B)=P(A∩B)/P(B)=0.4.")),
    _Check("probability.reverse", "probability",
        ("已知 P(A|B)=0.8，是否一定有 P(B|A)=0.8？", "If P(A|B)=0.8, must P(B|A) also equal 0.8?"), "B",
        ("不一定；反向条件概率还取决于 P(A) 和 P(B)。", "No. The reverse conditional probability also depends on P(A) and P(B)."),
        (("一定", "Yes"), ("不一定", "Not necessarily")), "transfer"),
    _Check("linear.dependent", "linear_algebra",
        ("向量 (1, 2) 与 (2, 4) 的关系是？", "What is the relation between vectors (1, 2) and (2, 4)?"), "A",
        ("第二个向量是第一个的 2 倍，因此线性相关。", "The second vector is twice the first, so they are linearly dependent."),
        (("线性相关", "Linearly dependent"), ("线性无关", "Linearly independent"))),
    _Check("linear.basis", "linear_algebra",
        ("(1, 0) 与 (0, 1) 是否构成 R² 的一组基？", "Do (1, 0) and (0, 1) form a basis of R²?"), "A",
        ("是。任意 (a,b)=a(1,0)+b(0,1)，且该表示唯一。", "Yes. Every (a,b)=a(1,0)+b(0,1), uniquely."),
        (("是", "Yes"), ("否", "No")), "transfer"),
)
_CHECK_BY_ID = {check.check_id: check for check in _CHECKS}


def _text(pair: tuple[str, str], language: Language) -> str:
    if language not in {"zh", "en"}:
        raise ValueError("Unsupported language")
    return pair[language == "en"]


def default_curriculum(language: Language = "zh") -> Curriculum:
    return Curriculum(
        nodes=tuple(ConceptNode(concept_id=key, title=_text(title, language)) for key, title in _TITLES.items()),
        prerequisites=tuple(Prerequisite(before=before, after=after) for before, after in _EDGES),
    )


def public_check(check_id: str, language: Language = "zh") -> CheckPrompt:
    check = _CHECK_BY_ID.get(check_id)
    if check is None:
        raise ValueError("Unknown learning check")
    return CheckPrompt(
        check_id=check_id, concept_id=check.concept_id, prompt=_text(check.prompt, language),
        response_type="choice" if check.choices else "number", purpose=check.purpose,
        choices=tuple(CheckChoice(id=chr(65 + i), text=_text(pair, language)) for i, pair in enumerate(check.choices)),
    )


def explain_check(check_id: str, language: Language = "zh") -> str:
    check = _CHECK_BY_ID.get(check_id)
    if check is None:
        raise ValueError("Unknown learning check")
    return _text(check.explanation, language)


def check_feedback(check_id: str, correctness: str, language: Language = "zh") -> str:
    check = _CHECK_BY_ID[check_id]
    if correctness == "explanation":
        return explain_check(check_id, language)
    if correctness == "unknown":
        return _text(("请选择一个选项。" if check.choices else "请输入一个数或分数。",
                      "Choose one option." if check.choices else "Enter a number or fraction."), language)
    prefix = _text(("这道题答对了。" if correctness == "correct" else "这道题还需要再检查。",
                    "This answer is correct. " if correctness == "correct" else "Recheck this answer. "), language)
    return prefix + explain_check(check_id, language)


def _events(observations: Sequence[LearningObservation | dict], retracted: Sequence[str] = ()) -> tuple[LearningObservation, ...]:
    if len(observations) > MAX_OBSERVATIONS or len(retracted) > MAX_OBSERVATIONS:
        raise ValueError("Learning observation budget exceeded")
    removed = set(retracted)
    unique: dict[str, LearningObservation] = {}
    for raw in observations:
        event = raw if isinstance(raw, LearningObservation) else LearningObservation.model_validate(raw)
        if event.event_id in removed:
            continue
        previous = unique.get(event.event_id)
        if previous is not None and previous != event:
            raise ValueError("An observation ID cannot be rewritten")
        unique[event.event_id] = event
    return tuple(sorted(unique.values(), key=lambda event: (
        datetime.fromisoformat(event.occurred_at).timestamp() if event.occurred_at else float("-inf"))))


def _independent_events(events: Sequence[LearningObservation]) -> tuple[LearningObservation, ...]:
    seen_attempts: set[str] = set()
    seen_items: set[str] = set()
    result = []
    for event in events:
        if event.event_type == "answer_exposed" and event.item_id:
            seen_items.add(event.item_id)
        if event.event_type != "attempt" or event.correct is None:
            continue
        repeated = bool((event.attempt_id and event.attempt_id in seen_attempts) or (event.item_id and event.item_id in seen_items))
        if event.attempt_id:
            seen_attempts.add(event.attempt_id)
        if event.item_id:
            seen_items.add(event.item_id)
        if (event.actor == "learner" and event.verification == "rule" and event.correct is not None
                and event.item_id and event.attempt_id and event.assistance == "none" and not repeated):
            result.append(event)
    return tuple(result)


def grade_check(
    check_id: str, answer: str, *, observation_id: str,
    prior_observations: Sequence[LearningObservation | dict] = (),
    helped: bool = False, answer_seen: bool = False, language: Language = "zh",
) -> CheckResult:
    check = _CHECK_BY_ID.get(check_id)
    if check is None:
        raise ValueError("Unknown learning check")
    if not isinstance(answer, str) or len(answer) > 240:
        raise ValueError("Answer must be a short string")
    normalized = answer.strip().replace("−", "-").replace("，", ",")
    correct = None
    if check.choices:
        if normalized.upper() in {chr(65 + i) for i in range(len(check.choices))}:
            correct = normalized.upper() == check.answer
    elif re.fullmatch(r"[+-]?(?:\d{1,12}(?:\.\d{1,12})?|\.\d{1,12})(?:/[+-]?\d{1,12})?", normalized):
        try:
            correct = Fraction(normalized) == Fraction(check.answer)
        except (ValueError, ZeroDivisionError):
            pass
    prior = _events(prior_observations)
    reused = any(event.item_id == check_id and (event.event_type == "answer_exposed"
                 or event.event_type == "attempt" and event.correct is not None) for event in prior)
    assistance = "answer_seen" if answer_seen or reused else "hint" if helped else "none"
    event = LearningObservation(
        event_id=observation_id, event_type="attempt", concept_id=check.concept_id,
        item_id=check_id, attempt_id=observation_id, answer=answer, correct=correct,
        verification="rule" if correct is not None else "none", assistance=assistance,
        occurred_at=datetime.now(UTC).isoformat(),
    )
    correctness = "unknown" if correct is None else "correct" if correct else "incorrect"
    return CheckResult(
        correctness=correctness, independent=correct is not None and assistance == "none",
        feedback=check_feedback(check_id, correctness, language), observation=event,
    )


def _concept(question: str) -> str:
    lowered = question.casefold()
    return next((key for key, aliases in _ALIASES.items() if any(alias in lowered for alias in aliases)), "open_inquiry")


def build_learning_plan(
    question: str, goal: Goal = "understand", observations: Sequence[LearningObservation | dict] = (), *,
    concept_id: str | None = None, language: Language = "zh",
    curriculum: Curriculum | dict | None = None, retracted_observation_ids: Sequence[str] = (),
) -> LearningPlan:
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError("A learning question must contain 1–2000 characters")
    if goal not in {"understand", "apply", "compare"}:
        raise ValueError("Unsupported learning goal")
    graph = default_curriculum(language) if curriculum is None else (
        curriculum if isinstance(curriculum, Curriculum) else Curriculum.model_validate(curriculum))
    target = concept_id or _concept(question)
    titles = {node.concept_id: node.title for node in graph.nodes}
    title = titles.get(target, _text(("当前问题", "Your question"), language))
    all_events = _events(observations)
    events = _events(all_events, retracted_observation_ids)
    live_ids = {event.event_id for event in events}
    independent = tuple(event for event in _independent_events(all_events) if event.event_id in live_ids)
    successes = [event for event in independent if event.correct and event.concept_id == target]
    failures = [event for event in independent if event.correct is False and event.concept_id == target]
    relevant = [event for event in events if event.concept_id == target and event.actor == "learner"]
    assisted = [event for event in relevant if event.event_type == "attempt" and event.verification == "rule"
                and event.correct is not None and event.assistance != "none"]
    state = "unknown"
    basis: tuple[str, ...] = ()
    if successes and failures:
        state, basis = "mixed_observations", tuple(event.event_id for event in (*successes, *failures))
    elif failures:
        state, basis = "needs_check", tuple(event.event_id for event in failures)
    elif successes:
        state, basis = "independent_observed", tuple(event.event_id for event in successes)
    elif assisted:
        state, basis = "assisted_only", tuple(event.event_id for event in assisted)

    default_action: Action = {"understand": "read", "apply": "worked_example", "compare": "compare_methods"}[goal]
    first_action: Action = {"mixed_observations": "clarify_conflict", "needs_check": "independent_check",
                           "assisted_only": "independent_check", "independent_observed": "transfer_check"}.get(state, default_action)
    reasons = {
        "unknown": ("还没有可用的独立作答记录，先从你选择的目标开始。", "There is no independent response record yet; start with your chosen goal."),
        "assisted_only": ("已有作答使用了帮助，下一题可以检查自己能否完成。", "The recorded response used help; a fresh check can show what you can do independently."),
        "needs_check": ("这次独立检查没有通过，可以用另一题定位需要澄清的条件。", "An independent check was incorrect; use a new problem to examine the relevant conditions."),
        "mixed_observations": ("独立作答的结果不一致，先比较题目条件再继续。", "The independent responses differ; compare their conditions before continuing."),
        "independent_observed": ("已有独立答对的记录，换一种情境继续检查；这还不代表稳定掌握。", "An independent response was correct; try a different context. This does not establish stable mastery."),
    }
    action_titles = {
        "read": ("读懂一个解释", "Read one explanation"),
        "worked_example": ("把方法用于一个例子", "Apply the method to an example"),
        "compare_methods": ("对照两种解释的条件", "Compare the conditions of two explanations"),
        "independent_check": ("用新题独立检查", "Try a fresh check independently"),
        "clarify_conflict": ("找出两次作答的差异", "Examine the difference between your responses"),
        "transfer_check": ("换个情境再试一次", "Try a different context"),
        "review_prerequisite": ("回看一个先修概念", "Revisit a prerequisite"),
        "choose_goal": ("决定下一步想弄清什么", "Choose what to explore next"),
    }
    steps: list[LearningStep] = []
    parents: dict[str, list[str]] = {}
    for edge in graph.prerequisites:
        parents.setdefault(edge.after, []).append(edge.before)
    positive_concepts = {event.concept_id for event in independent if event.correct}
    negative_concepts = {event.concept_id for event in independent if event.correct is False}
    usable_concepts = positive_concepts - negative_concepts

    def missing_prerequisite(key: str) -> str | None:
        for parent in sorted(parents.get(key, [])):
            if parent not in usable_concepts:
                return missing_prerequisite(parent) or parent
        return None

    prerequisite = missing_prerequisite(target) if state == "unknown" else None
    if prerequisite:
        prerequisite_events = [event for event in events if event.concept_id == prerequisite
                               and event.actor == "learner" and event.event_type == "attempt"
                               and event.verification == "rule" and event.correct is not None
                               and event.assistance != "none"]
        prerequisite_basis = tuple(event.event_id for event in prerequisite_events)
        prerequisite_reason = (
            ("这个先修概念已有借助帮助的作答记录；独立完成情况还不明确，可以回看或跳过。",
             "There is an assisted response on this prerequisite. Independent performance is still unclear; revisit it or skip ahead.")
            if prerequisite_basis else
            ("这是当前主题的一个建议入口；没有独立记录不等于你不会，可以选择跳过。",
             "This is a suggested starting point. No independent record does not mean you lack this knowledge; you can skip it.")
        )
        steps.append(LearningStep(
            step_id="prerequisite", concept_id=prerequisite, action="review_prerequisite", title=titles[prerequisite],
            reason=_text(prerequisite_reason, language), basis_observation_ids=prerequisite_basis,
        ))
    if state == "unknown" and not prerequisite and parents.get(target):
        prerequisite_support = tuple(event.event_id for event in independent
                                     if event.correct and event.concept_id in parents[target])
        basis = prerequisite_support
        if basis:
            reasons["unknown"] = (
                "先修概念已有独立作答记录；当前主题尚无记录，可以从你选择的目标继续。",
                "A prerequisite has an independent response record; this topic has none yet, so continue with your chosen goal.",
            )
    steps.append(LearningStep(
        step_id="focus", concept_id=target, action=first_action, title=_text(action_titles[first_action], language),
        reason=_text(reasons[state], language), basis_observation_ids=basis,
    ))
    next_action: Action = "independent_check" if first_action not in {"independent_check", "transfer_check"} else default_action
    if len(steps) < 3:
        steps.append(LearningStep(
            step_id="next", concept_id=target, action=next_action, title=_text(action_titles[next_action], language),
            reason=_text(("围绕你的原问题继续，记录自己的回答或还没解决的疑点。",
                          "Stay with your original question and record your own answer or an unresolved point."), language),
        ))
    used_ids = {event.item_id for event in all_events if event.item_id and (event.event_type == "answer_exposed"
                or event.event_type == "attempt" and event.correct is not None)}
    check = next((public_check(item.check_id, language) for item in _CHECKS
                  if item.concept_id == target and item.check_id not in used_ids), None)
    return LearningPlan(
        original_question=question, goal=goal, target_concept=target, concept_title=title,
        evidence_state=state, independent_successes=len(successes),
        basis_observation_ids=tuple(dict.fromkeys(ref for step in steps for ref in step.basis_observation_ids)),
        steps=tuple(steps), check=check,
        prerequisite_basis="authored_curriculum" if curriculum is None and target in titles
        else "provided_curriculum" if target in titles else "none",
    )


def catalog_manifest() -> dict:
    public = [public_check(item.check_id).model_dump(mode="json") for item in _CHECKS]
    return {"policy": POLICY, "check_ids": [item.check_id for item in _CHECKS], "count": len(_CHECKS),
            "public_prompt_digest": hashlib.sha256(repr(public).encode()).hexdigest(), "training": False}

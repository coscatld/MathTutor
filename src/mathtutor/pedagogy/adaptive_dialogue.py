"""Evidence-bounded DKT advice for ordinary chat, without grading students.

The source model predicts mapped ASSISTments skills.  It does not supply a
MathTutor mastery percentage or cover high-school calculus/statistics.  The
small policy below changes explanation granularity only when same-skill,
independent observations support the forecast.  It never changes requested
answer disclosure, language, mathematical authority, or curriculum coverage.
"""
from __future__ import annotations

import logging
import math
import re

from mathtutor.learning.knowledge_tracing.events import valid_events
from mathtutor.learning.knowledge_tracing.mapped_dkt import COARSE_TO_PRODUCT, forecast_for
from mathtutor.learning.skill_graph import SKILLS, skills_for_problem
from mathtutor.pedagogy.dkt_policy import dkt_may_adjust

logger = logging.getLogger(__name__)

_BOUNDARY = (
    "Counts describe verified, first independent whole-task observations on the current skill. "
    "Evidence bands describe sample quantity, not calibrated confidence. The source-domain DKT "
    "is not a MathTutor mastery grade; its learning effect is unverified. Assisted, post-solution, "
    "joint-skill and ungradable work cannot establish independent mastery of a skill."
)
_NEW_QUESTION = re.compile(
    r"^\s*(?:换题|新题|下一题|另(?:一|一个)(?:道)?(?:问题|题)|new\s+(?:question|problem)|switch\s+(?:to|topics?))\s*[:：,，]?", re.I)
_ORIGINAL_REFERENCE = re.compile(
    r"这(?:一?步|道题|题)|刚才|原题|上一步|^继续[。.!！?？\s]*$|"
    r"\b(?:this|that|previous)\s+(?:step|problem|question|equation|operation)\b|\bcontinue\b", re.I)
_OUTSIDE_SKILL_MAP = re.compile(
    r"导数|求导|微积分|极限|积分|概率|统计|圆锥曲线|椭圆|双曲线|向量|三角函数|对数函数|指数函数|"
    r"\b(?:derivatives?|differentiat(?:e|ing|ion)|calculus|limits?|integrals?|integration|probability|statistics|"
    r"confidence\s+intervals?|conic\s+sections?|ellipses?|hyperbolas?|trigonometry|vectors?)\b", re.I)
_REQUEST_CUE = re.compile(
    r"解释|讲解|讲讲|为什么|为何|怎么|想学|要学|学习|计算|求(?:解|导|极限|积分)?|证明|"
    r"\b(?:explain|why|how|what|teach|learn|help|differentiate|solve|calculate|find|want)\b", re.I)
_OLD_OR_REJECTED_FOCUS = re.compile(
    r"^(?:请)?(?:不要|不用|别|不想|不需要|不再)|^我(?:已经|早就|都)?(?:会|懂|理解|明白)|"
    r"^(?:please\s+)?(?:do\s+not|don[’']t|never|stop|avoid)\b|"
    r"^I\s+(?:(?:already|now)\s+)?(?:understand|know|have\s+mastered)\b", re.I)

# Deliberately narrower than the graph's search aliases: 'sign', 'coefficient',
# 'function', or a negative exponent does not establish an arithmetic target.
_EXPLICIT_FOCUS = {
    "signed_operations": r"有理数(?:的)?(?:四则)?运算|正负数(?:的)?(?:加减|乘除)|\bsigned\s+arithmetic\b|\binteger\s+arithmetic\b",
    "fraction_operations": r"分数(?:的)?(?:运算|加减|乘除)|通分|约分|\bfraction\s+arithmetic\b|\b(?:adding|subtracting|multiplying|dividing)\s+fractions\b|\bcommon\s+denominators?\b",
    "distributive_law": r"分配律|去括号|\bdistributive\s+(?:property|law)\b",
    "combine_like_terms": r"合并同类项|\bcombin(?:e|ing)\s+like\s+terms\b",
    "equality_preservation": r"等式(?:的)?性质|等式两边(?:同时|同做|同乘|同除)|\bpropert(?:y|ies)\s+of\s+equality\b",
    "linear_isolation": r"一元一次方程|一次方程|隔离未知数|\blinear\s+equations?\b|\bisolat(?:e|ing)\s+(?:the\s+)?(?:unknown|variable)\b",
    "substitution_check": r"代回(?:原式|原方程|原条件)?检验|代入(?:原式|原方程)检验|\bcheck\s+by\s+substitution\b",
    "factorisation": r"因式分解|\bfactori[sz]ation\b",
    "quadratic_discriminant": r"判别式|\bdiscriminant\b",
    "quadratic_roots": r"一元二次方程|二次方程(?:的)?(?:根|求解|求根)|求根公式|\bquadratic\s+(?:formula|equations?)\b",
    "system_elimination": r"方程组消元|消元法|\belimination\s+method\b",
    "system_substitution": r"方程组代入|代入法|\bsubstitution\s+method\b",
    "system_completeness": r"方程组(?:的)?(?:全部解|完整解)|\bcomplete\s+solution\s+of\s+(?:a\s+)?system\b",
}


def _known_skills(skill_ids) -> tuple[str, ...]:
    values = []
    for raw in skill_ids or ():
        skill = COARSE_TO_PRODUCT.get(str(raw), str(raw))
        if skill in SKILLS and skill not in values:
            values.append(skill)
    return tuple(values)


def _parsed_skills(text: str) -> tuple[str, ...]:
    if not text or len(text) > 2000:
        return ()
    from mathtutor.application.input_normalizer import normalize_input
    from mathtutor.solving.parser import parse_problem
    surface = re.sub(
        r"^\s*(?:(?:please\s+)?(?:solve|simplify|calculate)\b|(?:请|帮我)?(?:计算|求解|解方程|化简|展开|解不等式|因式分解|求根|求值))\s*[:：]?\s*",
        "", text, flags=re.I)
    # normalize_input removes broader task wrappers such as 求极限/证明.
    # Those wrappers must not turn an unsupported calculus/proof task into
    # a covered bare polynomial. Only a complete expression is parsed here.
    if re.search(r"[\u4e00-\u9fff]", surface):
        return ()
    outcome = parse_problem(normalize_input(surface).normalized)
    return _known_skills(skills_for_problem(outcome.problem)) if outcome.kind == "parsed" else ()


def _focus_surface(text: str) -> str:
    """Prefer the current requested operation over old or rejected topics."""
    clauses = [clause.strip() for clause in re.split(r"[。！？.!?；;\n，,]|\bbut\b|但是|不过|而是", text, flags=re.I)
               if clause.strip()]
    active = [clause for clause in clauses if not _OLD_OR_REJECTED_FOCUS.search(clause)]
    requests = [clause for clause in active if _REQUEST_CUE.search(clause)]
    return requests[-1] if requests else active[-1] if active else ""


def resolve_dialogue_skills(text: str, *, problem=None, original_question: str = "") -> tuple[str, ...]:
    """Identify an instructional focus; never infer that it is mastered.

    ``problem`` must be the current server-bound problem, not a client label.
    A clear new-question command prevents reuse of the old binding.  The
    parser is used only on complete supported expressions, not on a formula
    extracted from an otherwise unsupported high-school question.
    """
    from mathtutor.application.teaching_intent import current_request_text
    current = current_request_text(str(text or "")).strip()
    new_question = _NEW_QUESTION.match(current)
    refers_back = bool(_ORIGINAL_REFERENCE.search(current)) and not new_question
    current = current[new_question.end():].strip() if new_question else current
    focus_surface = _focus_surface(current)
    if not focus_surface:
        return ()
    # A new unsupported target takes precedence over an old known skill or
    # binding. A local algebra question *within* a larger discussion can still
    # identify its specific operation in the latest requested clause.
    if _OUTSIDE_SKILL_MAP.search(focus_surface):
        return ()
    if refers_back and problem is not None:
        grounded = _known_skills(skills_for_problem(problem))
        if grounded:
            return grounded
    if refers_back and original_question:
        grounded = _parsed_skills(str(original_question))
        if grounded:
            return grounded
    grounded = _parsed_skills(current)
    if grounded:
        return grounded
    # An explicit question about an operation can narrow an unsupported
    # discussion to that operation. Do not project this onto the entire task.
    focus = tuple(skill for skill, pattern in _EXPLICIT_FOCUS.items() if re.search(pattern, focus_surface, re.I))
    if focus:
        return focus
    if refers_back and original_question:
        return tuple(skill for skill, pattern in _EXPLICIT_FOCUS.items()
                     if re.search(pattern, _focus_surface(str(original_question)), re.I))
    return ()


def _evidence(history, student_id: str, skills: tuple[str, ...]) -> dict:
    selected = set(skills)
    rows = {skill: {"correct": set(), "incorrect": set()} for skill in skills}
    extra = {kind: set() for kind in ("assisted", "post_solution", "joint", "ungradable", "diagnostic", "repeat")}
    timeline = {skill: [] for skill in skills}
    # Owner filtering precedes correction/replay: one student's event ID or
    # invalidation cannot influence another student's summary.
    accepted = valid_events([event for event in history if event.student_id == str(student_id)])
    for event in accepted:
        if event.event_type != "attempt_assessed" or event.duplicate_response:
            continue
        bound = _known_skills(event.skill_ids)
        targets = selected.intersection(bound)
        if not targets:
            continue
        identity = event.problem_revision
        if event.provenance_uncertain or event.correctness in {None, "unknown"} or event.evidence_kind == "unknown":
            extra["ungradable"].add(identity)
        elif event.task_purpose in {"diagnostic", "error_analysis"} or event.completion_scope != "full_problem" or event.correctness == "partial":
            extra["diagnostic"].add(identity)
        elif event.evidence_kind in {"assisted", "post_solution"}:
            extra[event.evidence_kind].add(identity)
        elif event.prior_task_attempt:
            extra["repeat"].add(identity)
        elif event.independent_target:
            if len(event.skill_ids) != 1:
                extra["joint"].add(identity)
                # A joint whole-task outcome does not attribute proficiency
                # or an error to each skill, even when the DKT can encode it.
                continue
            for skill in targets:
                if identity not in rows[skill][event.correctness]:
                    rows[skill][event.correctness].add(identity)
                    timeline[skill].append(event.correctness)
    correct = set().union(*(row["correct"] for row in rows.values())) if rows else set()
    incorrect = set().union(*(row["incorrect"] for row in rows.values())) if rows else set()
    return {
        "independent_correct": len(correct), "independent_incorrect": len(incorrect),
        "independent_items": len(correct | incorrect),
        **{f"{kind}_items": len(values) for kind, values in extra.items()},
        "by_skill": {skill: {"independent_correct": len(row["correct"]),
                              "independent_incorrect": len(row["incorrect"]),
                              "independent_items": len(row["correct"] | row["incorrect"]),
                              "recent_independent": timeline[skill][-3:]}
                     for skill, row in rows.items()},
    }


def _base_context(skills: tuple[str, ...], evidence: dict) -> dict:
    n = evidence["independent_items"]
    return {"schema": "adaptive_dialogue_v1", "skill_ids": list(skills),
            "evidence_counts": evidence, "evidence_count": n,
            "evidence_reliability": "none" if n == 0 else "limited" if n < 5 else "repeated_observations",
            "strategy": "neutral", "strategy_skill_ids": [], "reason_codes": [],
            "forecast": {"status": "unavailable", "probability": None, "controls_teaching": False},
            "boundary": _BOUNDARY}


async def build_adaptive_context(student_state, owner_id: str, skill_ids) -> dict:
    """Use the loaded local checkpoint and trusted owner-scoped event history.

    No state writes, model endpoint calls, raw responses, or reference answers
    are exposed. Missing/corrupt model state leaves ordinary chat available.
    """
    skills = _known_skills(skill_ids)
    empty = _base_context(skills, _evidence([], str(owner_id), skills))
    if student_state is None or not owner_id:
        empty["reason_codes"] = ["STUDENT_STATE_UNAVAILABLE"]
        return empty
    try:
        history = await student_state.events(str(owner_id))
        history = [event for event in history if event.student_id == str(owner_id)]
        context = _base_context(skills, _evidence(history, str(owner_id), skills))
    except Exception:
        logger.warning("Adaptive dialogue evidence unavailable")
        empty["reason_codes"] = ["EVIDENCE_UNAVAILABLE"]
        return empty
    if not skills:
        context["forecast"]["status"] = "unsupported_target"
        context["reason_codes"] = ["NO_SUPPORTED_CURRENT_SKILL"]
        return context
    package = getattr(student_state, "source_model", None)
    if package is None:
        context["reason_codes"] = ["MODEL_UNAVAILABLE"]
        return context
    try:
        forecast = forecast_for(package, history, skills)
        context["forecast"] = {key: forecast.get(key) for key in (
            "probability", "probability_source", "coverage_status", "controls_teaching", "mapping_version",
            "target_skill_ids", "target_history_updates", "target_history_by_skill", "history_updates",
            "mapped_product_skills", "unmapped_skill_ids", "partial_coverage", "learning_effect_verified")}
        context["forecast"]["source_model"] = {key: package.identity.get(key) for key in ("package_id", "model_sha256", "format")}
        context["forecast"]["status"] = ("available" if forecast.get("probability") is not None else "unsupported_target")
        if not dkt_may_adjust(forecast, skill_ids=skills):
            context["reason_codes"] = ["FORECAST_NOT_ELIGIBLE"]
            return context
        probability = forecast["probability"]
        if not isinstance(probability, (int, float)) or isinstance(probability, bool) or not math.isfinite(probability) or not 0 <= probability <= 1:
            context["forecast"]["status"] = "invalid"
            context["reason_codes"] = ["FORECAST_INVALID"]
            return context
        per_skill = context["evidence_counts"]["by_skill"]
        target_counts = forecast.get("target_history_by_skill") or {}
        eligible = [skill for skill in skills if target_counts.get(skill, 0) >= 1]
        low_supported = [skill for skill in eligible if per_skill[skill]["independent_incorrect"] >= 2]
        if probability < 0.45 and low_supported:
            context["strategy"] = "smaller_step"
            context["strategy_skill_ids"] = low_supported
            context["reason_codes"] = ["MAPPED_DKT_LOW_AND_REPEATED_INDEPENDENT_DIFFICULTY"]
        elif probability > 0.75 and eligible and all(
            per_skill[skill]["independent_correct"] >= 3
            and per_skill[skill]["recent_independent"] == ["correct"] * 3
            and per_skill[skill]["independent_correct"] / max(1, per_skill[skill]["independent_items"]) >= 0.75
            for skill in eligible
        ):
            context["strategy"] = "lighter_scaffold"
            context["strategy_skill_ids"] = eligible
            context["reason_codes"] = ["MAPPED_DKT_HIGH_AND_REPEATED_INDEPENDENT_SUCCESS"]
        else:
            context["reason_codes"] = ["INSUFFICIENT_CORROBORATING_SKILL_EVIDENCE"]
        return context
    except Exception:
        logger.warning("Adaptive dialogue local forecast unavailable")
        context["forecast"] = {"status": "error", "probability": None, "controls_teaching": False}
        context["strategy"] = "neutral"
        context["reason_codes"] = ["FORECAST_UNAVAILABLE"]
        return context


def adaptive_instruction(context: dict | None, learner: dict | None = None) -> str:
    """Translate a bounded strategy into style advice, not student labels."""
    if not context or context.get("schema") != "adaptive_dialogue_v1":
        return ""
    strategy = context.get("strategy")
    if strategy not in {"smaller_step", "lighter_scaffold"}:
        return ""
    counts = context.get("evidence_counts") or {}
    n = counts.get("independent_items", 0)
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return ""
    targets = [skill for skill in _known_skills(context.get("strategy_skill_ids"))
               if skill in _known_skills(context.get("skill_ids"))]
    by_skill = counts.get("by_skill") or {}
    if not targets:
        return ""
    focus = "；".join(
        f"{SKILLS[skill].label}：首次独立整题正确 {by_skill.get(skill, {}).get('independent_correct', 0)} 道、"
        f"错误 {by_skill.get(skill, {}).get('independent_incorrect', 0)} 道"
        for skill in targets)
    quantity = "证据有限" if n < 5 else "已有多次观察，仍需后续独立检测"
    advice = ("把当前相关操作拆小一档，明确写出这一步的依据与检查方法；不要直接给学生贴能力标签。"
              if strategy == "smaller_step" else
              "可少解释一档已有多次独立正确记录的基础操作，把篇幅留给学生当前不清楚的联系；必要推理、条件与最终所求仍须写全。")
    return (f"\n应用的当前技能记录包含 {n} 道首次独立整题作答；{quantity}。"
            f"本轮只调整以下基础操作的讲解步幅：{focus}。这些是编排依据，不需向学生复述。"
            "本地来源域模型与这些记录仅用于调整讲解步幅，不代表已校准的学生掌握度，也不证明教学效果。"
            + advice + "这不能覆盖学生明确要求的完整解答、只提示、语言、格式或长度；"
            "要求完整解答时仍完整回答，要求提示时不提前泄露答案，不额外强制提问或布置练习。"
            "帮助后完成、看答案后作答、自述理解和未经核验的讲解均不能当作独立掌握证据。"
            "学生当前明确困惑或追问某步原因时，优先解释他所问的原因，不能因为历史正确就略过当前疑问。"
            "保持原题学段和条件，不能因为模型只覆盖基础代数就把高中问题改成低年级题。"
            "不要向学生报告模型概率或说其已经掌握、能力不足。")


__all__ = ["resolve_dialogue_skills", "build_adaptive_context", "adaptive_instruction"]

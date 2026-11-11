"""Bounded, exact diagnostic probes; matches describe response patterns, not minds.

The finite catalog is checked through the product Parser/Solver/Verifier gate.
Independent responses can support or contradict executable rules.  No posterior
probability, mastery score or stable psychological label is inferred here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import re
from typing import Mapping, Sequence

POLICY_VERSION = "diagnostic_probes_v1"
MAX_DIAGNOSTIC_QUESTIONS = 3
MAX_CATALOG_SIZE = 64
DOMAINS = ("fraction_addition", "signed_subtraction")
DOMAIN_LABELS = {
    "fraction_addition": {"zh": "分数加法", "en": "Adding fractions"},
    "signed_subtraction": {"zh": "有符号数的减法", "en": "Subtracting signed numbers"},
}
RULE_LABELS = {
    "correct": {"zh": "本次计算符合运算规则", "en": "These answers follow the operation rules"},
    "add_across": {"zh": "作答中出现了分子、分母分别相加的模式", "en": "Answers match adding numerators and denominators separately"},
    "multiply_denominators": {"zh": "作答中出现了分母相乘但分子未通分的模式", "en": "Answers match multiplying denominators without scaling numerators"},
    "keep_left_denominator": {"zh": "作答中出现了直接保留第一个分母的模式", "en": "Answers match keeping the first denominator"},
    "ignore_subtracted_sign": {"zh": "作答中出现了忽略减数符号的模式", "en": "Answers match ignoring the sign of the number being subtracted"},
    "always_negative_difference": {"zh": "作答中出现了把绝对值之差总写成负数的模式", "en": "Answers match always making the difference of magnitudes negative"},
    "add_instead": {"zh": "作答中出现了把减法当作加法的模式", "en": "Answers match adding instead of subtracting"},
}
RULES = {
    "fraction_addition": ("correct", "add_across", "multiply_denominators", "keep_left_denominator"),
    "signed_subtraction": ("correct", "ignore_subtracted_sign", "always_negative_difference", "add_instead"),
}


@dataclass(frozen=True, slots=True)
class Probe:
    probe_id: str
    domain: str
    family: str
    purpose: str
    statement: str
    operands: tuple[int, ...]
    answer: Fraction
    predictions: tuple[tuple[str, Fraction], ...]
    prompt_zh: str = "计算下面的式子，填写结果。"
    prompt_en: str = "Calculate the expression and enter its value."
    relation: str = "new_instance"


def format_answer(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


# Deliberately narrower than the full math parser: no expressions, powers,
# executable text, invisible separators or huge integer work at this boundary.
_RESPONSE = re.compile(r"[+-]?(?:[0-9]{1,9}(?:\.[0-9]{1,9})?|\.[0-9]{1,9})(?:/[+-]?[0-9]{1,9})?\Z", re.ASCII)


def parse_response(text: object) -> Fraction | None:
    if not isinstance(text, str) or len(text) > 48:
        return None
    value = text.strip().replace("−", "-")
    value = re.sub(r"\s*/\s*", "/", value)
    if not _RESPONSE.fullmatch(value):
        return None
    try:
        if "/" in value:
            numerator, denominator = value.split("/")
            return Fraction(numerator) / int(denominator)
        return Fraction(value)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _verified(probe: Probe) -> Probe:
    from mathtutor.domain.problem import MathProblem
    from mathtutor.solving.parser import parse_problem
    from mathtutor.solving.solver import solve_problem
    from mathtutor.solving.verifier import verify

    parsed = parse_problem(probe.statement).problem
    if parsed is None:
        raise ValueError("Probe could not be parsed")
    problem = MathProblem.canonicalize(problem_type=parsed.problem_type,
        normalized_ast=parsed.normalized_ast, display_latex=parsed.display_latex)
    candidate = solve_problem(problem, parsed).candidate
    if candidate is None or verify(problem, candidate).verdict != "VERIFIED":
        raise ValueError("Probe did not pass exact verification")
    answer = candidate.final_answer
    if answer.get("kind") == "rational":
        value = answer["value"]
    elif answer.get("kind") == "roots" and len(answer["roots"]) == 1:
        value = answer["roots"][0]["value"]
    else:
        raise ValueError("Probe does not have one exact rational answer")
    if Fraction(value["n"], value["d"]) != probe.answer:
        raise ValueError("Independent probe answer disagrees with verifier")
    return probe


def _fraction(a: int, b: int, c: int, d: int, purpose: str, index: int) -> Probe:
    answer = Fraction(a, b) + Fraction(c, d)
    predictions = (("correct", answer), ("add_across", Fraction(a+c, b+d)),
        ("multiply_denominators", Fraction(a+c, b*d)), ("keep_left_denominator", Fraction(a+c, b)))
    family = "equal_denominators" if b == d else "unequal_denominators"
    return Probe(f"fraction_addition:{purpose}:{index:02}", "fraction_addition", family,
        purpose, f"{a}/{b} + {c}/{d}", (a,b,c,d), answer, predictions)


def _signed(a: int, b: int, purpose: str, index: int) -> Probe:
    answer = Fraction(a-b)
    predictions = (("correct", answer), ("ignore_subtracted_sign", Fraction(a-abs(b))),
        ("always_negative_difference", Fraction(-abs(abs(a)-abs(b)))), ("add_instead", Fraction(a+b)))
    family = f"{'negative' if a < 0 else 'positive'}_{'negative' if b < 0 else 'positive'}"
    return Probe(f"signed_subtraction:{purpose}:{index:02}", "signed_subtraction", family,
        purpose, f"({a}) - ({b})", (a,b), answer, predictions)


@lru_cache(maxsize=len(DOMAINS))
def catalog(domain: str) -> tuple[Probe, ...]:
    if domain not in DOMAINS:
        raise ValueError("Unsupported diagnostic domain")
    probes: list[Probe] = []
    if domain == "fraction_addition":
        args = [(1,b,1,d) for b in (2,3,4,5) for d in (2,3,4,5)]
        args += [(2,b,1,d) for b in (3,4,5) for d in (3,4,5)]
        probes += [_fraction(*values, "diagnostic", i) for i,values in enumerate(args)]
        reviews = [(1,6,1,7),(2,7,3,7),(3,8,1,4),(1,9,2,3),
                   (2,5,3,10),(3,7,1,2),(1,8,2,5),(2,9,1,6)]
        probes += [_fraction(*values, "review", i) for i,values in enumerate(reviews)]
        for i,(a,b,c,d) in enumerate(reviews):
            answer = Fraction(c,d) - Fraction(a,b)
            probes.append(Probe(f"{domain}:transfer:{i:02}", domain, "missing_addend", "transfer",
                f"x + {a}/{b} = {c}/{d}", (a,b,c,d), answer, (),
                "求等式中 x 的值。", "Find the value of x in the equation.", "missing_addend"))
    else:
        args = [(a,b) for a in (-9,-6,-3,3,6,9) for b in (-9,-6,-3,3,6,9)]
        probes += [_signed(*values, "diagnostic", i) for i,values in enumerate(args)]
        reviews = [(-8,-2),(-2,-8),(7,-4),(-7,4),(4,7),(8,2),(-5,-1),(1,-5)]
        probes += [_signed(*values, "review", i) for i,values in enumerate(reviews)]
        for i,(a,b) in enumerate(reviews):
            probes.append(Probe(f"{domain}:transfer:{i:02}", domain, "missing_minuend", "transfer",
                f"x - ({b}) = ({a})", (a,b), Fraction(a+b), (),
                "求等式中 x 的值。", "Find the value of x in the equation.", "missing_minuend"))
    if len(probes) > MAX_CATALOG_SIZE or len({p.statement for p in probes}) != len(probes):
        raise ValueError("Probe catalog exceeds bounds or contains duplicate tasks")
    return tuple(_verified(probe) for probe in probes)


def get_probe(probe_id: str) -> Probe:
    if not isinstance(probe_id, str) or len(probe_id) > 80:
        raise ValueError("Invalid probe identity")
    domain = probe_id.split(":", 1)[0]
    for probe in catalog(domain):
        if probe.probe_id == probe_id:
            return probe
    raise ValueError("Unknown probe identity")


def public_probe(probe: Probe) -> dict:
    return {"probe_id": probe.probe_id, "domain": probe.domain, "family": probe.family,
        "purpose": probe.purpose, "statement": probe.statement, "prompt_zh": probe.prompt_zh,
        "prompt_en": probe.prompt_en, "relation": probe.relation, "policy_version": POLICY_VERSION}


def feedback_for(probe: Probe) -> dict:
    answer = format_answer(probe.answer)
    if probe.purpose == "transfer":
        zh = "把已知项移到等号另一边时使用相反运算，再代回原等式检查。"
        en = "Use the inverse operation to isolate x, then substitute it into the original equation."
    elif probe.domain == "fraction_addition":
        zh = "先把两个分数通分，分母相同时相加分子，最后约分。"
        en = "Use a common denominator, add the numerators, then simplify."
    else:
        zh = "减去一个数等于加上它的相反数，再根据符号计算。"
        en = "Subtracting a number is adding its opposite; then calculate with the signs."
    return {"answer": answer, "explanation_zh": zh, "explanation_en": en}


def assess_response(probe_id: str, text: str) -> dict:
    probe = get_probe(probe_id)
    value = parse_response(text)
    if value is None:
        return {"correctness": "unknown", "normalized_answer": None,
                "matching_rules": [], "feedback": None}
    return {"correctness": "correct" if value == probe.answer else "incorrect",
        "normalized_answer": format_answer(value),
        "matching_rules": [rule for rule,predicted in probe.predictions if predicted == value],
        "feedback": feedback_for(probe)}


def diagnostic_state(domain: str, observations: Sequence[Mapping]) -> dict:
    if domain not in DOMAINS or len(observations) > MAX_DIAGNOSTIC_QUESTIONS:
        raise ValueError("Invalid diagnostic scope or question budget")
    candidates = set(RULES[domain])
    admitted = 0
    seen: set[str] = set()
    contradiction = False
    for observation in observations:
        probe = get_probe(observation.get("probe_id"))
        if probe.domain != domain or probe.purpose != "diagnostic" or probe.probe_id in seen:
            raise ValueError("Mixed or repeated diagnostic evidence")
        seen.add(probe.probe_id)
        value = parse_response(observation.get("answer"))
        if observation.get("independent") is not True or value is None:
            continue
        admitted += 1
        matching = {rule for rule,predicted in probe.predictions if value == predicted}
        candidates &= matching
        contradiction |= not candidates
    supported = next(iter(candidates)) if admitted >= 2 and len(candidates) == 1 and not contradiction else None
    status = "pattern_supported" if supported else "uncertain" if contradiction or len(observations) == MAX_DIAGNOSTIC_QUESTIONS else "collecting"
    return {"status": status, "candidates": [r for r in RULES[domain] if r in candidates],
        "supported_rule": supported, "answered": len(observations), "independent_observations": admitted,
        "contradiction": contradiction, "inference": "provisional_response_pattern"}


def choose_probe(domain: str, observations: Sequence[Mapping], excluded_ids: Sequence[str] = ()) -> Probe | None:
    state = diagnostic_state(domain, observations)
    if state["status"] != "collecting":
        return None
    excluded = set(excluded_ids) | {o["probe_id"] for o in observations}
    eligible = [p for p in catalog(domain) if p.purpose == "diagnostic" and p.probe_id not in excluded]
    if not eligible:
        return None
    candidates = state["candidates"]
    families = {get_probe(o["probe_id"]).family for o in observations}
    def score(probe):
        predictions = dict(probe.predictions)
        counts = Counter(predictions[r] for r in candidates)
        separation = len(candidates)**2 - sum(n*n for n in counts.values())
        return separation, probe.family not in families, len(set(predictions.values()))
    return max(eligible, key=score)


def choose_followup(domain: str, purpose: str, excluded_ids: Sequence[str] = ()) -> Probe | None:
    if purpose not in {"review", "transfer"}:
        raise ValueError("Invalid follow-up purpose")
    excluded = set(excluded_ids)
    return next((p for p in catalog(domain) if p.purpose == purpose and p.probe_id not in excluded), None)

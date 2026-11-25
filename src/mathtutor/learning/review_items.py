"""Unseen follow-ups for the three review days. The frozen diagnostic catalog keeps its IDs."""
from fractions import Fraction
from functools import lru_cache

from mathtutor.learning import diagnostic_probes as probes
from mathtutor.learning.linear_review import DOMAIN as LINEAR


@lru_cache(maxsize=1)
def linear_items():
    items = []
    for i in range(1, 10):
        root, added = i + 2, i + 1
        rows = (
            ("review", "linear_value", f"3*x+{added}={3*root+added}", root),
            ("transfer", "unknown_on_right", f"{2*root+added}=2*x+{added}", root),
            ("transfer", "variable_both_sides", f"4*x+{added}=2*x+{2*root+added}", root),
            ("transfer", "distribute", f"3*(x+{added})={3*(root+added)}", root),
        )
        for purpose, family, statement, answer in rows:
            items.append(probes._verified(probes.Probe(
                f"{LINEAR}:variant:{family}:{i:02}", LINEAR, family, purpose, statement, (i,),
                Fraction(answer), (), "求方程中 x 的值。", "Solve the equation for x.",
                family if purpose == "transfer" else "new_instance",
            )))
    return tuple(items)


@lru_cache(maxsize=2)
def variants(domain):
    result = []
    for i, item in enumerate(p for p in probes.catalog(domain) if p.purpose == "review"):
        if domain == "fraction_addition":
            a, b, c, d = item.operands
            first, second = Fraction(a, b), Fraction(c, d)
            structures = (
                ("missing_minuend", f"x - {a}/{b} = {c}/{d}", first + second),
                ("two_equal_parts", f"{a}/{b} + 2*x = {c}/{d}", (second - first) / 2),
            )
        else:
            a, b = item.operands
            structures = (
                ("missing_subtrahend", f"({a}) - x = ({b})", Fraction(a - b)),
                ("two_equal_parts", f"({a}) - 2*x = ({b})", Fraction(a - b, 2)),
            )
        for family, statement, answer in structures:
            probe = probes.Probe(
                f"{domain}:variant:{family}:{i:02}", domain, family, "transfer",
                statement, item.operands, answer, (), "求等式中 x 的值。",
                "Find the value of x in the equation.", family,
            )
            result.append(probes._verified(probe))
    return tuple(result)


def get_probe(probe_id):
    if ":variant:" in probe_id:
        domain = probe_id.split(":", 1)[0]
        for probe in linear_items() if domain == LINEAR else variants(domain):
            if probe.probe_id == probe_id:
                return probe
        raise ValueError("Unknown review variant")
    return probes.get_probe(probe_id)


def assess(probe, answer):
    if ":variant:" not in probe.probe_id:
        return probes.assess_response(probe.probe_id, answer)
    if probe.domain == LINEAR and isinstance(answer, str):
        # The UI asks for x. A solved assignment is also a valid numerical response.
        sides = answer.strip().split("=")
        if len(sides) == 2 and "x" in (sides[0].strip(), sides[1].strip()):
            answer = sides[1] if sides[0].strip() == "x" else sides[0]
    value = probes.parse_response(answer)
    if value is None:
        return {"correctness": "unknown"}
    return {
        "correctness": "correct" if value == probe.answer else "incorrect",
        "normalized_answer": probes.format_answer(value), "matching_rules": [],
    }


def feedback(probe):
    if probe.domain != LINEAR:
        return probes.feedback_for(probe)
    return {"answer": probes.format_answer(probe.answer),
            "explanation_zh": "对等式两边做相同的运算，求出 x 后代回原式。",
            "explanation_en": "Apply the same operation to both sides, then substitute your value for x."}


@lru_cache(maxsize=64)
def _revision(statement):
    from mathtutor.application.llm_candidate_generator import candidate_problem_revision
    return candidate_problem_revision(statement)


def seen_in_tutoring(probe, seen_revisions):
    return bool(seen_revisions) and _revision(probe.statement) in seen_revisions


def choose(domain, phase, round_index, served_ids, attempts, seen_revisions=()):
    seen = set(served_ids)
    previous = get_probe(attempts[-1]["probe_id"]) if attempts else None
    # A failed structural problem gets another example of that structure for practice.
    structural_practice = phase == "practice" and previous and previous.purpose == "transfer"
    if domain == LINEAR:
        families = ("unknown_on_right", "variable_both_sides", "distribute")
        family = previous.family if structural_practice else families[round_index] if phase == "transfer" else "linear_value"
        pool = [p for p in linear_items() if p.family == family]
    elif phase == "transfer" or structural_practice:
        if structural_practice:
            family = previous.family
        else:
            families = (("missing_addend", "missing_minuend", "two_equal_parts") if domain == "fraction_addition"
                        else ("missing_minuend", "missing_subtrahend", "two_equal_parts"))
            family = families[round_index]
        pool = [p for p in (*probes.catalog(domain), *variants(domain)) if p.purpose == "transfer" and p.family == family]
    else:
        pool = [p for p in probes.catalog(domain) if p.purpose == "review"]
    candidates = [p for p in pool if p.probe_id not in seen and not seen_in_tutoring(p, seen_revisions)]
    if not candidates:
        return None
    # Prefer a distinct result from the preceding feedback. After an arithmetic error,
    # keep the same sign/denominator condition while changing the operands.
    target = previous.family if previous and phase == "practice" and attempts[-1]["correctness"] == "incorrect" else None
    prior_answers = {get_probe(probe_id).answer for probe_id in served_ids}
    return max(candidates, key=lambda p: (
        previous is None or p.answer != previous.answer, p.family == target, p.answer not in prior_answers,
    ))

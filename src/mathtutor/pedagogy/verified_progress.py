"""Distinguish verified mathematical validity from new student work.

Equation forms retain their two canonical sides: reducing everything to a
root set would erase legitimate alternative routes. Only trusted verifier
claims can contribute evidence. Older records can be read without rewriting
them; an unreadable old equation makes novelty unknown rather than assumed.
"""
from __future__ import annotations

from mathtutor.domain.hashing import content_hash
from mathtutor.solving import nodes as n
from mathtutor.solving.parser import parse_problem, parse_linear_equation_fragment

PROGRESS_POLICY_VERSION = "mt-verified-progress-v1"
NEW_PROGRESS = frozenset({"new_verified_step", "new_requirement"})


def _key(context, kind, evidence):
    return kind + ":" + content_hash({
        "version": PROGRESS_POLICY_VERSION,
        "problem_revision": context.get("problem_revision"), "evidence": evidence,
    })


def _equation_keys(context, ast):
    equations = ast.equations if isinstance(ast, n.LinearSystem) else (ast,)
    return {_key(context, "equation", sorted(
        (n.to_dict(eq.lhs), n.to_dict(eq.rhs)), key=content_hash))
        for eq in equations if isinstance(eq, n.Equation)}


def _parsed_equation_keys(context, text):
    parsed = parse_problem(text)
    if parsed.kind != "parsed":
        parsed = parse_linear_equation_fragment(text)
    return _equation_keys(context, parsed.problem.ast) if parsed.kind == "parsed" else set()


def _original_equation_keys(context):
    # Display LaTeX is not always accepted by the student grammar (e.g.
    # x^{2}); use the original persisted canonical task whenever available.
    payload = context.get("task_context", {}).get("normalized_representation")
    if isinstance(payload, dict):
        try:
            return _equation_keys(context, n.from_dict(payload))
        except (KeyError, TypeError, ValueError, n.MathDomainError):
            pass
    return _parsed_equation_keys(context, context.get("display_text", ""))


def _root_value(value):
    # Root subsets use either a rational or the quadratic solver's root
    # wrapper. These are the same verified fact, not two new requirements.
    if isinstance(value, dict) and value.get("kind") == "rational":
        return value["value"]
    return value


def _evidence(context, claims, text):
    equations, requirements = set(), set()
    equation_history_complete = True
    for claim in claims:
        kind = claim.get("claim")
        if kind in {"equivalent_equation", "valid_system_intermediate"}:
            keys = set()
            if isinstance(claim.get("equation"), dict):
                try:
                    keys = _equation_keys(context, n.from_dict(claim["equation"]))
                except (KeyError, TypeError, ValueError, n.MathDomainError):
                    pass
            # Compatibility for existing attestations without equation AST.
            keys = keys or _parsed_equation_keys(context, text)
            equations.update(keys)
            equation_history_complete &= bool(keys)
        elif kind == "variable_value":
            requirements.add(_key(context, "requirement", {
                "variable": claim.get("variable"), "value": claim.get("value")}))
        elif kind == "root_subset":
            requirements.update(_key(context, "requirement", {"root": _root_value(value)})
                                for value in claim.get("roots", []))
    return equations, requirements, equation_history_complete


def classify_progress(context, record):
    """Return additive audit metadata; never change the mathematical verdict.

    A newly verified canonical equation is a new step, even if it does not
    complete a named goal. A repeat, side swap or +0 normalization is not.
    This is a narrow work-evidence policy, not a claim of comprehension or
    useful instructional effect for every possible equivalent transformation.
    """
    result = {"progress_policy_version": PROGRESS_POLICY_VERSION,
              "progress_kind": "unknown", "semantic_evidence_keys": []}
    if record["math_validity"] != "valid":
        return result
    equations, requirements, _ = _evidence(context, record["verified_steps"], record["raw_text"])
    known_equations = _original_equation_keys(context)
    known_requirements = set()
    history_complete = bool(known_equations)
    for prior in context.get("progress", []):
        prior_equations, prior_requirements, complete = _evidence(
            context, prior.get("verified_claims", []), prior.get("text", ""))
        known_equations.update(prior_equations)
        known_requirements.update(prior_requirements)
        history_complete &= complete
    keys = equations | requirements
    if record["task_completion"] == "complete":
        keys.add(_key(context, "requirement", {"task_completion": "complete"}))
        result["progress_kind"] = "restatement" if context.get("lifecycle") == "completed" else "new_requirement"
    elif requirements - known_requirements:
        result["progress_kind"] = "new_requirement"
    elif equations - known_equations:
        result["progress_kind"] = "new_verified_step" if history_complete else "unknown"
    elif keys:
        result["progress_kind"] = "restatement"
    result["semantic_evidence_keys"] = sorted(keys)
    return result

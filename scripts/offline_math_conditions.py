"""Bounded checks of explicitly mapped claims. No natural-language classifier.

Only the existing verifier can emit VERIFIED, and only for its candidate.
Counterexamples and parameter reasoning do not certify a whole prose answer.
"""
from fractions import Fraction
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.solving import nodes as n
from mathtutor.solving.parser import parse_problem
from mathtutor.solving.solver import solve_problem
from mathtutor.solving.verifier import verify


def check_expression(expression):
    parsed = parse_problem(expression)
    row = dict(expression=expression, parse_status=parsed.kind, verification="UNKNOWN", reason=parsed.reason)
    if parsed.kind != "parsed":
        return row
    p = parsed.problem
    problem = MathProblem.canonicalize(p.problem_type, p.normalized_ast, p.display_latex)
    outcome = solve_problem(problem, p)
    row.update(problem_type=p.problem_type, solve_status=outcome.kind, reason=outcome.reason)
    if outcome.candidate:
        decision = verify(problem, outcome.candidate)
        row.update(verification=decision.verdict, final_answer=outcome.candidate.final_answer,
                   checks=[c.model_dump() for c in decision.checks],
                   verification_scope="this concrete solver candidate only; not the associated prose or symbolic parameter family")
    return row


def counterexamples():
    roots = check_expression("x^2+x=0")
    assert roots["verification"] == "VERIFIED"
    values = [Fraction(r["value"]["n"],r["value"]["d"]) for r in roots["final_answer"]["roots"]]
    # Claim-to-expression mapping is an explicit AI review annotation, not a
    # keyword detector; the exact root signs are evaluated independently.
    product = values[0] * values[1]
    original = parse_problem("x=1").problem
    poly = n.equation_difference(original.ast, "x")
    residual_at_zero = sum(v * Fraction(0)**degree for degree, v in poly.items())
    zero = n.evaluate(n.mul(n.num(0), n.num(1)))
    try:
        n.div(n.num(1), n.num(0))
    except n.MathDomainError:
        division = "REJECTED_DIVISION_BY_ZERO"
    else:
        raise AssertionError("Existing bounded arithmetic accepted division by zero")
    return dict(
        opposite_signs=dict(parameters=dict(a=1,b=1,c=0), candidate=roots,
            root_values=[str(v) for v in values], root_product=str(product),
            claim="c=0,b!=0 gives one positive and one negative root", claim_refuted=not product < 0,
            prose_verification="UNKNOWN; only this mapped assertion has a counterexample"),
        multiply_zero=dict(original="x=1", transformed="0*x=0*1", witness_x=0,
            original_residual=str(residual_at_zero), transformed_residual=zero.n,
            preserves_forward_implication=True, equivalent=False,
            assessment="EXACT_COUNTEREXAMPLE; not a verifier attestation for a general transformation"),
        denominator=dict(expression="x/(x-1)=1/(x-1)", general_check=check_expression("x/(x-1)=1/(x-1)"),
            cleared_equation=check_expression("x=1"), excluded_candidate=1,
            substituted_denominator="1-1=0", bounded_domain_check=division,
            assessment="candidate solves cleared equation but original undefined; general rational equation remains UNKNOWN"))


def report():
    cases = [(0,2,4,"linear x=-2"), (0,0,1,"contradiction; empty set"),
        (0,0,0,"identity; all real x"), (1,1,0,"0,-1; not opposite signs"),
        (1,-1,0,"0,1; not opposite signs"), (2,0,0,"zero double root"),
        (1,0,-4,"two real roots -2,2"), (1,0,4,"no real roots"), (-1,0,4,"two real roots -2,2")]
    rows = []
    for a,b,c,reference in cases:
        expression = f"({a})*x^2+({b})*x+({c})=0"
        row = dict(parameters=dict(a=a,b=b,c=c), reference=reference,
            reference_status="PROVISIONAL_AI", result=check_expression(expression))
        if a == b == 0:
            row["arithmetic_residual"] = check_expression(str(c))
            row["limitation"] = "Constant equation classification is outside the solver family; UNKNOWN even though the scalar residual is exactly evaluable"
        rows.append(row)
    return dict(version="math-condition-regression/1", cases=rows, counterexamples=counterexamples(),
        symbolic_family_check=check_expression("a*x^2+b*x+c=0"),
        disclosure="Finite concrete cases do not prove all symbolic parameter cases or certify whole answers")

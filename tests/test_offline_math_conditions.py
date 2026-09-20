"""Concrete solver/domain tests plus review provenance; never live quality."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from fractions import Fraction
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from offline_math_conditions import check_expression, counterexamples, report
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.solving.parser import parse_problem
from mathtutor.solving.solver import solve_problem
from mathtutor.solving.verifier import verify
from mathtutor.solving import nodes as n

OUT=ROOT/"tests/fixtures/sanitized_rag_release/offline"


@pytest.mark.parametrize("expression, roots", [
    ("0*x^2+2*x+4=0",[-2]), ("x^2+x=0",[-1,0]),
    ("x^2-x=0",[0,1]), ("2*x^2=0",[0]),
    ("x^2-4=0",[-2,2]), ("x^2+4=0",[]), ("-x^2+4=0",[-2,2]),
])
def test_degenerate_concrete_roots_use_actual_verifier(expression, roots):
    row=check_expression(expression)
    assert row["verification"]=="VERIFIED"
    assert [Fraction(r["value"]["n"],r["value"]["d"]) for r in row["final_answer"]["roots"]]==roots


@pytest.mark.parametrize("expression",["0*x^2+0*x+1=0","0*x^2+0*x+0=0","a*x^2+b*x+c=0","x/(x-1)=1/(x-1)"])
def test_outside_supported_equation_families_remains_unknown(expression):
    assert check_expression(expression)["verification"]=="UNKNOWN"


def test_double_root_is_supported_by_coefficients_not_two_distinct_roots():
    parsed=parse_problem("2*x^2=0").problem
    coeffs=n.equation_difference(parsed.ast,"x")
    assert coeffs.get(0,0)==coeffs.get(1,0)==0 and coeffs[2]!=0
    assert len(check_expression("2*x^2=0")["final_answer"]["roots"])==1


def test_zero_multiplication_has_forward_implication_but_not_equivalence():
    result=counterexamples()["multiply_zero"]
    assert result["original_residual"]=="-1" and result["transformed_residual"]==0
    assert result["preserves_forward_implication"] and not result["equivalent"]
    assert n.evaluate(n.mul(n.num(0),n.num(37))).n==0


def test_cleared_denominator_candidate_is_not_certified_for_original():
    result=counterexamples()["denominator"]
    assert result["cleared_equation"]["verification"]=="VERIFIED"
    assert result["general_check"]["verification"]=="UNKNOWN"
    assert result["bounded_domain_check"]=="REJECTED_DIVISION_BY_ZERO"


def test_actual_verifier_rejects_division_by_zero_step():
    parsed=parse_problem("2*x+4=0").problem
    problem=MathProblem.canonicalize(parsed.problem_type,parsed.normalized_ast,parsed.display_latex)
    candidate=solve_problem(problem,parsed).candidate
    steps=copy.deepcopy(candidate.steps)
    divide=next(s for s in steps if s["transform"]["kind"]=="divide_all")
    divide["transform"]["value"]={"n":0,"d":1}
    bad=MathSolutionCandidate.canonicalize(problem_id=problem.problem_id,strategy=candidate.strategy,
                                          steps=steps,final_answer=candidate.final_answer)
    decision=verify(problem,bad)
    assert decision.verdict!="VERIFIED"
    assert any(c.status=="failed" for c in decision.checks)


def test_provenance_and_scores_stay_separate():
    for group, expected in [("expression-fixed",14),("degenerate-fixed",3)]:
        review=json.loads((OUT/f"{group}-review.json").read_text(encoding="utf-8"))
        assert review["generating_version"]=="0.4.1" and review["review_version"]=="0.4.2"
        assert not review["original_B_scores_reused"] and review["faithfulness_macro"] is None
        assert len(review["rows"])==expected
        for row in review["rows"]:
            assert row["answer_sha256"]==hashlib.sha256(row["final_answer"].encode()).hexdigest()
            assert row["human_review_status"]=="PENDING" and row["faithfulness_score"] is None
            assert row["request_record_ids"] and row["actual_visible_evidence"] and row["claims"]


def test_corrected_and_erroneous_sources_have_distinct_cohorts_and_hashes():
    fixture=ROOT/"tests/fixtures/rag_math_conditions_v1"
    manifest=json.loads((fixture/"manifest.json").read_text(encoding="utf-8"))
    errors=json.loads((fixture/"source-error-cases.json").read_text(encoding="utf-8"))
    assert errors and manifest["version"]!="hard-corpus/2"
    for doc in manifest["documents"]:
        assert hashlib.sha256((fixture/"normal"/doc["filename"]).read_bytes()).hexdigest()==doc["corrected_sha256"]
        if doc["replacements"]:
            assert doc["historical_sha256"]!=doc["corrected_sha256"]
    assert all(e["cohort"]=="SOURCE_CONTAINS_ERROR" and e["evidence_support"]=="DIRECT" and e["mathematics"].startswith("FALSE") for e in errors)


def test_history_and_budget_byte_identical():
    for path,digest in json.loads((OUT/"history-lock.json").read_text(encoding="utf-8")).items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,path


def test_minimal_review_packet_does_not_contain_provider_payloads():
    packet=json.loads((OUT/"human-review/packet.json").read_text(encoding="utf-8"))
    assert len(packet["answers"])==17
    assert any(c["mathematical_correctness"]=="AI_FALSE" for c in packet["answers"][0]["claims"])
    def visit(value):
        if isinstance(value,dict):
            assert not set(value)&{"messages","parameters","reasoning_content","api_key","Authorization","usage"}
            for v in value.values(): visit(v)
        elif isinstance(value,list):
            for v in value: visit(v)
    visit(packet)

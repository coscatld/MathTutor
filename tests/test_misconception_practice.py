"""Every diagnosed error class the verifier reports can steer the next item."""
import pytest

from mathtutor.application.evidence_projection import teaching_practice_focus
from mathtutor.learning.skill_graph import SKILLS
from mathtutor.pedagogy.teaching_plan import error_guidance


def context(family, codes, *, repeated=False):
    counts = {code: 2 for code in codes} if repeated else {}
    records = [] if repeated else [{"math_validity": "invalid", "misconception_candidates": list(codes)}]
    return {"problem_type": family, "learner_evidence": {"verified_error_counts": counts}, "assessments": records}


@pytest.mark.parametrize("family, code, skill", [
    ("linear", "wrong_operation", "equality_preservation"),
    ("linear", "sign_flip", "signed_operations"),
    ("quadratic", "missing_root", "quadratic_roots"),
    ("quadratic", "extraneous_root", "substitution_check"),
    ("linear_system", "missing_root", "system_completeness"),
    ("linear_system", "wrong_operation", "system_elimination"),
    ("polynomial", "wrong_value", "combine_like_terms"),
    ("arithmetic", "wrong_value", "signed_operations"),
])
def test_each_verified_error_maps_to_a_real_skill(family, code, skill):
    for repeated in (False, True):
        focus, guidance = teaching_practice_focus(context(family, [code], repeated=repeated))
        assert focus == skill and focus in SKILLS and guidance


def test_unverified_or_unmapped_errors_do_not_steer_practice():
    assert teaching_practice_focus({"problem_type": "linear", "learner_evidence": {"verified_error_counts": {"sign_flip": 1}},
                                    "assessments": []}) == ("", "")
    assert teaching_practice_focus(context("quadratic", ["wrong_family"])) == ("", "")


def test_sign_errors_take_priority_like_the_diagnosis_rules():
    assert teaching_practice_focus(context("linear", ["wrong_value", "sign_flip"]))[0] == "signed_operations"


@pytest.mark.parametrize("code, phrase", [("missing_root", "漏解"), ("extraneous_root", "代回原式检验")])
def test_guidance_names_only_the_verified_error_class(code, phrase):
    assert phrase in error_guidance([code], repeated=True) + error_guidance([code])
    assert error_guidance(["wrong_family"]) == ""

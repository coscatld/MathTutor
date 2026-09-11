from mathtutor.pedagogy.student_evidence_view import assessment_view, progress_view


def test_expected_roots_and_missing_answers_do_not_enter_writer_context():
    record = {"assessment_id": "a", "raw_text": "2x=4", "math_validity": "valid",
              "verified_steps": [{"claim": "equivalent_equation", "root": {"n": 2, "d": 1}}],
              "invalid_claims": [{"claim": "root_value", "actual": 3, "expected": 2}],
              "remaining_requirements": [{"requirement": "state_roots", "expected_roots": [2], "missing_roots": [2]}]}
    projected = assessment_view([record])[0]
    assert projected["raw_text"] == "2x=4"
    assert projected["verified_steps"] == [{"claim": "equivalent_equation"}]
    assert projected["invalid_claims"] == [{"claim": "root_value", "actual": 3}]
    assert projected["remaining_requirements"] == [{"requirement": "state_roots"}]
    assert "root" in record["verified_steps"][0]  # no mutation of verifier ledger


def test_actual_student_coordinate_is_retained_but_equivalence_certificate_is_not():
    rows = [{"assessment_id": "a", "text": "x=3", "verified_claims": [
        {"claim": "variable_value", "variable": "x", "value": {"n": 3, "d": 1}},
        {"claim": "equivalent_equation", "roots": [3, -3]}]}]
    projected = progress_view(rows)[0]
    assert projected["verified_claims"][0] == rows[0]["verified_claims"][0]
    assert projected["verified_claims"][1] == {"claim": "equivalent_equation"}

"""Exact arithmetic, evidence and resource boundaries for diagnostic probes."""
from dataclasses import replace
from fractions import Fraction
import pytest

from mathtutor.learning import diagnostic_probes as dp


def independent_answer(probe):
    if probe.domain == "fraction_addition":
        a,b,c,d = probe.operands
        sign = -1 if probe.purpose == "transfer" else 1
        return Fraction(c*b + sign*a*d, b*d)
    a,b = probe.operands
    return Fraction(a+b if probe.purpose == "transfer" else a-b)


@pytest.mark.parametrize("domain", dp.DOMAINS)
def test_catalog_gate_and_independent_arithmetic(domain):
    items = dp.catalog(domain)
    assert len(items) <= 64
    assert len({p.probe_id for p in items}) == len(items)
    for purpose in ("review", "transfer"):
        assert len([p for p in items if p.purpose == purpose]) >= 8
    for probe in items:
        assert probe.answer == independent_answer(probe)
        assert dp.assess_response(probe.probe_id, str(probe.answer))["correctness"] == "correct"
        assert dp.assess_response(probe.probe_id, str(probe.answer+1))["correctness"] == "incorrect"
        if probe.purpose == "transfer":
            assert "x" in probe.statement and "=" in probe.statement
            assert probe.relation.startswith("missing_")
            assert not probe.predictions


@pytest.mark.parametrize("text,value", [(" 3 / 6 ",Fraction(1,2)),("−4",Fraction(-4)),(".25",Fraction(1,4)),("+3.5",Fraction(7,2)),("1/-2",Fraction(-1,2)),("0",Fraction(0))])
def test_numeric_normalization(text,value):
    assert dp.parse_response(text) == value


@pytest.mark.parametrize("text", ["",None,2,"x=2","1+1","2**8","1e9","1/0","NaN","inf","9"*49,"1000000000","\\frac{1}{2}","１２","1\u200b/2","__import__('os')","1/2/3"])
def test_unknown_is_not_incorrect_or_answer_exposure(text):
    assert dp.parse_response(text) is None
    assessment = dp.assess_response("fraction_addition:diagnostic:00", text)
    assert assessment == {"correctness":"unknown","normalized_answer":None,"matching_rules":[],"feedback":None}


@pytest.mark.parametrize("domain", dp.DOMAINS)
def test_public_contract_contains_no_answer_predictions_or_solver_output(domain):
    for probe in dp.catalog(domain):
        payload = dp.public_probe(probe)
        assert set(payload) == {"probe_id","domain","family","purpose","statement","prompt_zh","prompt_en","relation","policy_version"}
        assert payload["statement"] == probe.statement


@pytest.mark.parametrize("domain", dp.DOMAINS)
def test_active_selection_identifies_every_known_rule_without_single_response_claim(domain):
    for rule in dp.RULES[domain]:
        observations = []
        for _ in range(3):
            probe = dp.choose_probe(domain, observations)
            if probe is None:
                break
            response = dict(probe.predictions)[rule]
            observations.append({"probe_id":probe.probe_id,"answer":str(response),"independent":True})
            if len(observations) == 1:
                assert dp.diagnostic_state(domain, observations)["supported_rule"] is None
        state = dp.diagnostic_state(domain, observations)
        assert state["supported_rule"] == rule
        assert state["inference"] == "provisional_response_pattern"
        assert dp.choose_probe(domain, observations) is None


def test_colliding_answers_keep_competing_rules_and_contradiction_retracts_support():
    probe = dp.get_probe("fraction_addition:diagnostic:00") # 1/2 + 1/2
    first = {"probe_id":probe.probe_id,"answer":"1/2","independent":True}
    assert dp.diagnostic_state(probe.domain,[first])["candidates"] == ["add_across","multiply_denominators"]
    next_probe = dp.choose_probe(probe.domain,[first])
    assert dict(next_probe.predictions)["add_across"] != dict(next_probe.predictions)["multiply_denominators"]
    other = {"probe_id":next_probe.probe_id,"answer":"99","independent":True}
    state = dp.diagnostic_state(probe.domain,[first,other])
    assert state["status"] == "uncertain" and state["contradiction"]
    assert state["supported_rule"] is None


def test_helped_responses_and_unknown_input_do_not_narrow_evidence():
    domain = "signed_subtraction"
    observations = [{"probe_id":f"{domain}:diagnostic:{i:02}","answer":"99","independent":False} for i in range(3)]
    state = dp.diagnostic_state(domain,observations)
    assert state["candidates"] == list(dp.RULES[domain])
    assert state["independent_observations"] == 0
    assert state["status"] == "uncertain"
    assert dp.choose_probe(domain, observations) is None


def test_replays_cross_domain_and_budget_are_rejected():
    obs = {"probe_id":"signed_subtraction:diagnostic:00","answer":"0","independent":True}
    with pytest.raises(ValueError): dp.diagnostic_state("signed_subtraction",[obs,obs])
    with pytest.raises(ValueError): dp.diagnostic_state("fraction_addition",[obs])
    with pytest.raises(ValueError): dp.diagnostic_state("signed_subtraction",[obs]*4)
    with pytest.raises(ValueError): dp.diagnostic_state("unknown",[])
    with pytest.raises(ValueError): dp.get_probe("signed_subtraction:diagnostic:99")


def test_followup_exclusions_and_type_are_enforced():
    used = []
    for _ in range(8):
        probe = dp.choose_followup("signed_subtraction", "transfer", used)
        assert probe is not None and probe.probe_id not in used
        used.append(probe.probe_id)
    assert dp.choose_followup("signed_subtraction","transfer",used) is None
    with pytest.raises(ValueError): dp.choose_followup("signed_subtraction","diagnostic")


def test_catalog_gate_refuses_wrong_answer_even_if_expression_itself_is_valid():
    probe = dp.catalog("fraction_addition")[0]
    with pytest.raises(ValueError,match="disagrees"):
        dp._verified(replace(probe, answer=probe.answer+1))

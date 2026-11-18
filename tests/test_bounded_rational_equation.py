from contextlib import closing
from fractions import Fraction
import json
import sqlite3
from types import SimpleNamespace

import pytest

from mathtutor.application.bounded_rational_equation import rational_equation_receipt
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.domain.hashing import content_hash
from mathtutor.solving.quadratic_inequality import from_payload
from mathtutor.api.product_state import get_product_state
from test_product_math_boundary import NoInventedAnswer
from test_tutor_p0 import client_at, send, summary


@pytest.mark.parametrize("text,accepted,excluded", [
    ("(x^2-1)/(x-1)=2，且 x≠1", [], ["1"]),
    ("(x^2-1)/(x-1)=3", ["2"], ["1"]),
    ("(x^2-4)/(x-2)=0", ["-2"], ["2"]),
    ("(x^2-4)/(x-2)=3", ["1"], ["2"]),
    ("1/(x-1)=2", ["3/2"], []),
    ("x/x=2", [], ["0"]),
    ("x/(x^2+1)=0", ["0"], []),
    ("1/(x^2+1)=0", [], []),
    ("(x^2-1)/(x-1)=3，且 x>2", [], ["1", "2"]),
    ("(x^2-1)/(x-1)=3，且 x≥2", ["2"], ["1"]),
    (r"\frac{x^2-1}{x-1}=3", ["2"], ["1"]),
])
async def test_exact_rational_equations_filter_domain_before_accepting_roots(text, accepted, excluded):
    receipt = await rational_equation_receipt(text, InProcessVerificationBackend())
    assert receipt and receipt["status"] == "verified"
    assert [str(interval.lo) for interval in from_payload(receipt["solution_set"])] == accepted
    assert [root["root"] for root in receipt["excluded_roots"]] == excluded
    assert receipt["receipt_hash"] == content_hash({key: value for key, value in receipt.items() if key != "receipt_hash"})


@pytest.mark.parametrize("text,excluded,minimum", [
    ("x/x=1", 0, None), ("0/(x-1)=0", 1, None), ("0*(1/x)=0", 0, None),
    ("1/(1/x)=x", 0, None), ("(x^2-1)/(x-1)=x+1，且 x>2", 1, 2),
])
async def test_identities_keep_divisor_exceptions_even_after_cancellation(text, excluded, minimum):
    receipt = await rational_equation_receipt(text, InProcessVerificationBackend())
    assert receipt and not receipt["cleared_coefficients"]
    intervals = from_payload(receipt["solution_set"])
    for numerator in range(-8, 13):
        point = Fraction(numerator, 2)
        assert any(interval.contains(point) for interval in intervals) == (
            point != excluded and (minimum is None or point > minimum))


@pytest.mark.parametrize("text", [
    "(x^2-1)/(x-1)=3，且x是整数", "(x^2-1)/(x-1)=3，且y>0",
    "(x^2-1)/(x-1)=3，且x>2或x<0", "(x^2-1)/(x-1)=3，假设更多条件成立",
    "1/(x-1)=x^3", "1/(x^2-2)=0", "1/(x-1)=a", "1/(x-1)=",
    "1/(x-x)=0", "1/0+x=1", "1/(__import__('os'))=x", "1/(x-1)=x^99999",
])
async def test_unknown_conditions_or_excess_complexity_never_drop_out_of_the_receipt(text):
    assert await rational_equation_receipt(text, InProcessVerificationBackend()) is None


async def test_polynomial_verifier_rejection_cannot_be_overridden_by_substitution():
    class Rejected:
        async def verify(self, problem, candidate):
            return SimpleNamespace(verdict="REJECTED")
    assert await rational_equation_receipt("1/(x-1)=2", Rejected()) is None


def test_chat_shows_complete_domain_and_extraneous_root_steps_without_model_or_mastery(tmp_path):
    db = tmp_path / "rational.db"
    question = "(x^2-1)/(x-1)=2，且 x≠1"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.chat_responder = NoInventedAnswer()
        frames = send(ws, "send_message", "rational", {"text": question, "network_search": True})
        body = next(frame["payload"]["final_text"] for frame in frames if frame["event_type"] == "assistant_complete")
        assert all(fragment in body for fragment in ("定义域", "候选根：x=1", "分母为零", "舍去", "已核验结论：无解"))
        assert summary(client)["problem_context"]["display_text"] == question
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute("SELECT count(*) FROM learning_events").fetchone()[0] == 0
            saved = json.loads(connection.execute("SELECT continuation_context FROM conversation_messages WHERE role='tutor'").fetchone()[0])
        receipt = saved["math_boundary"]["formula_receipt"]
        assert receipt["scope"] == "bounded_rational_equation" and receipt["answer"] == "无解"
        assert send(ws, "send_message", "rational", {"text": question, "network_search": True}) == frames
    with client_at(db) as client:
        assert summary(client)["problem_context"]["display_text"] == question
        assert summary(client)["messages"][-1]["content"] == body

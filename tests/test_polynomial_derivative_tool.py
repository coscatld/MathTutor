"""General local derivative checks, with no live model or benchmark answers."""

import json

import pytest

from mathtutor.application.math_verification import verify_math
from test_math_tool_loop import answer, bind, tool_call
from test_tutor_p0 import client_at, send


class NoEquationBackend:
    """A derivative must use the exact local path, not an equation solver."""

    async def verify(self, *_):
        raise AssertionError("polynomial derivative fell through to the equation verifier")


@pytest.mark.parametrize("expression, proposed", [
    ("derivative(5,x)", "0"),
    ("derivative(x^7,x)", "7x^6"),
    ("derivative(2*x^4-3*x^2+5*x-8,x)", "8*x^3-6*x+5"),
    ("derivative((3*x-2)^3,x)", "9*(3*x-2)^2"),
    ("derivative((x+2)*(x-3),x)", "2*x-1"),
    ("derivative(x^4/3+0.25*x^2,x)", "4*x^3/3+x/2"),
    ("derivative(-x^4,x)", "-4*x^3"),
    ("derivative(7*t^3-2*t,t)", "21*t^2-2"),
])
async def test_exact_derivatives_without_float_sampling(expression, proposed):
    checked = await verify_math(NoEquationBackend(), expression, proposed)
    assert checked.status == "verified"
    assert checked.signals == ("exact_polynomial_derivative",)


@pytest.mark.parametrize("expression, proposed", [
    ("derivative((2*x+1)^4,x)", "4*(2*x+1)^3"),  # omitted chain factor
    ("derivative(x^6,x)", "6*x^6"),  # forgot to lower exponent
    ("derivative(0.3*x^3,x)", "0.899999999999*x^2"),  # no tolerance passes
    ("derivative(x^3,x)", "3*x^2+0.0000001"),
    ("derivative(2*x^4-5*x,x)", "8*x^3+5"),  # sign error
])
async def test_derivative_mismatches_are_refuted(expression, proposed):
    checked = await verify_math(NoEquationBackend(), expression, proposed)
    assert checked.status == "refuted"
    assert checked.signals == ("polynomial_derivative_mismatch",)


@pytest.mark.parametrize("expression, proposed", [
    ("derivative(ln(x)/x,x)", "(1-ln(x))/x^2"),
    ("derivative(sin(x),x)", "cos(x)"),
    ("derivative(abs(x),x)", "1"),
    ("derivative(x/x,x)", "0"),  # a removed singularity is not a polynomial
    ("derivative(0*(1/x),x)", "0"),  # multiplication must not hide a domain hole
    ("derivative(x^2,x)", "(2*x*x)/x"),  # proposed answer has a new domain hole
    ("derivative(a*x^3,x)", "3*a*x^2"),
    ("derivative(x^3,x)", "3*y^2"),
    ("derivative(x^13,x)", "13*x^12"),
    ("derivative(2^(2^12),x)", "0"),  # no huge exponent evaluation
    ("derivative((999999999999^12)^12,x)", "0"),
    ("derivative(x^0,x)", "0"),  # does not silently decide 0^0/domain conventions
    ("derivative(x^2,x)", "2*x=0"),
    ("derivative(x^2,x)", "2*x; open('secret')"),
    ("derivative(x^2,x)", "__import__('os').system('false')"),
    ("derivative(x^2,x)", "[2*x]"),
    ("derivative(x^2,x)", "2*x " + "+0" * 101),
    ("derivative(x^2)", "2*x"),
])
async def test_unsupported_or_ambiguous_claims_remain_unchecked(expression, proposed):
    checked = await verify_math(NoEquationBackend(), expression, proposed)
    assert checked.status == "unchecked"
    assert checked.reason


def test_real_tutor_tool_path_returns_derivative_receipt(tmp_path):
    requests = []
    replies = [tool_call("derivative((2*x-3)^3,x)", "3*(2*x-3)^2"),
               answer("复合函数求导还要乘内层的导数 2；先把链式法则各部分写出来。")]
    with client_at(tmp_path / "calculus.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "derivative-check", {"text": "如何对 (2*x-3)^3 求导？"})
    receipt = json.loads(next(message for message in requests[1]["messages"]
                              if message["role"] == "tool")["content"])
    assert receipt == {"status": "refuted", "signals": ["polynomial_derivative_mismatch"]}
    final = next(frame for frame in frames if frame["event_type"] == "assistant_complete")["payload"]
    assert final["status"] == "COMPLETED"
    assert final["tool_calls_count"] == 1
    assert "链式法则" in final["final_text"]

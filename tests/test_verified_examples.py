import asyncio
import hashlib
import time

import pytest

from mathtutor.application.verification_backend import InProcessVerificationBackend, VerificationBackpressureError
from mathtutor.application.verified_examples import render_verified_examples, verified_examples
from mathtutor.domain.dual_channel_gate import MathState, SourceState
from mathtutor.infrastructure.verifier_worker import VerifierWorkerManager


class RecordingBackend(InProcessVerificationBackend):
    def __init__(self):
        self.calls = []

    async def verify(self, problem, candidate):
        self.calls.append((problem, candidate))
        return await super().verify(problem, candidate)


@pytest.mark.asyncio
@pytest.mark.parametrize("question,family,answer", [
    ("计算 1/2+1/3。", "arithmetic", r"\frac{5}{6}"),
    ("请解 $2x+3=7$。", "linear", "x = 2"),
    ("展开 $(x+1)^2$。", "polynomial", "x^{2} + 2x + 1"),
    ("求解 $x^2-5x+6=0$。", "quadratic", "x = 2 或 x = 3"),
    (r"解 $\begin{cases}x+y=3\\x-y=1\end{cases}$。", "linear_system", r"x=2,\quad y=1"),
    ("解 x+y=3; x-y=1。", "linear_system", r"x=2,\quad y=1"),
    ("求解 $x^2+1=0$。", "quadratic", "无实数解"),
    (r"Compute $\frac{1}{2}+\frac{1}{3}$.", "arithmetic", r"\frac{5}{6}"),
    (r"计算 \(1+2\)。", "arithmetic", "3"),
    (r"计算 \[1+2\]。", "arithmetic", "3"),
    (r"计算 $$1+2$$。", "arithmetic", "3"),
])
async def test_real_solver_and_verifier_preserve_exact_source_range(question, family, answer):
    backend = RecordingBackend()
    examples = await verified_examples(question, backend, disclosure_allowed=True)
    assert len(examples) == len(backend.calls) == 1
    ex = examples[0]
    problem, candidate = backend.calls[0]
    assert (ex.problem_type, ex.answer_latex) == (family, answer)
    assert question[ex.span_start:ex.span_end] == ex.source_text
    assert ex.question_hash == hashlib.sha256(question.encode()).hexdigest()
    assert ex.problem_hash == problem.content_hash and ex.candidate_hash == candidate.payload_hash
    assert len(ex.verification_hash) == 64 and ex.verification_policy
    assert ex.source_state is SourceState.NONE and ex.math_state is MathState.CORRECT
    assert ex.steps and answer in render_verified_examples(examples)


@pytest.mark.asyncio
@pytest.mark.parametrize("question,formula,answer", [
    ("What about 1/2×1/3?", "1/2×1/3", r"\frac{1}{6}"),
    ("Please explain 2x+3=7.", "2x+3=7", "x = 2"),
    ("Show an example: 2x+3=7.", "2x+3=7", "x = 2"),
    ("Why 1+2?", "1+2", "3"),
    ("Compute 2+3, please.", "2+3", "5"),
    ("Please expand (x+1)^2.", "(x+1)^2", "x^{2} + 2x + 1"),
    ("What is the value of 0.5+1.25?", "0.5+1.25", r"\frac{7}{4}"),
    (r"What about \frac{1}{2}\times\frac{1}{3}?", r"\frac{1}{2}\times\frac{1}{3}", r"\frac{1}{6}"),
    (r"Compute \frac{1}{2}+\frac{1}{3} please.", r"\frac{1}{2}+\frac{1}{3}", r"\frac{5}{6}"),
])
async def test_ordinary_english_and_complete_tex_keep_the_exact_formula_span(question, formula, answer):
    examples = await verified_examples(question, RecordingBackend(), disclosure_allowed=True)
    assert len(examples) == 1
    ex = examples[0]
    assert ex.source_text == formula == question[ex.span_start:ex.span_end]
    assert (ex.span_start, ex.span_end) == (question.index(formula), question.index(formula) + len(formula))
    assert ex.answer_latex == answer


@pytest.mark.asyncio
@pytest.mark.parametrize("formula", [
    "sin(x)+1", "log(x)+1", "log (x)+1", "sin x+1", "foo(x)+1", "foo (x)+1", "foo x+1",
    "1e3+2", "1e-3+2", "2E+3+1", "e^2+1", "foo2x+1", "x1+2", "x_1+2", "item1+2",
    "xfoo(1)+2", "2+3foo", "x.foo+1", "1+2.foo", r"\sin(x)+1", r"\unknown{x}+1",
    r"\unknown (x)+1", r"\unknown x+1", r"\fracbad{1}{2}+3", r"\mathrm{x}+1", r"\dfrac{1}{2}+1",
])
async def test_unsupported_prefixes_and_identifiers_cannot_certify_a_supported_substring(formula):
    backend = RecordingBackend()
    assert await verified_examples(f"Compute {formula} please.", backend, disclosure_allowed=True) == ()
    assert backend.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "这位作者的观点最可靠。", "请证明 $x^2+1>0$。", "若 x>0，解 $x^2=9$。",
    "给个提示，别给答案：$x+1=2$。", "求 $x^2=9$ 的正根。", "是否 $2+3=99$？",
    "计算 $2 3+1$。", "计算 $1/0+1$。", "计算 $sin(x)+1$。", "计算 sin x+1。",
    "计算 2+3%。", "计算 |x+1|。", "计算 √4+1。", r"计算 $\begin{matrix}1&2\\3&4\end{matrix}$。",
    "Solve $x^2=9$ with x even.", "设 x 为2，计算 $x+1$。",
    "$8/2(2+2)$", "$3/4x$", "$3/(4)x$", "$6÷2(1+2)$", "$i^2+1$", "$e^2+1$",
    "计算 $1234567890123+1$。", "计算 $2^4097$。", "计算 $2^2000$。",
    "计算 $" + "(" * 15 + "1+2" + ")" * 15 + "$。",
    "计算 $" + "+".join(["1"] * 40) + "$。",
    "计算 $" + "1+" * 100 + "1$。", "算" * 4001 + " $1+2$。",
    "分别算 $1+2$、$2+3$、$3+4$。", "解 $x=2$，$x=3$。",
])
async def test_ambiguous_unsupported_contextual_or_over_budget_inputs_have_no_receipt(question):
    backend = RecordingBackend()
    assert await verified_examples(question, backend, disclosure_allowed=True) == ()
    assert len(backend.calls) <= 2


@pytest.mark.asyncio
async def test_disclosure_is_opt_in_and_separate_examples_remain_separate():
    backend = RecordingBackend()
    assert await verified_examples("解 $x+1=2$", backend) == ()
    assert backend.calls == []
    q = "分别计算 $1+2$、$2+3$。这些计算不说明社区作者的观点。"
    examples = await verified_examples(q, backend, disclosure_allowed=True)
    assert [e.answer_latex for e in examples] == ["3", "5"]
    text = render_verified_examples(examples, language="en")
    assert text.startswith("### MathTutor local verification") and "only these calculations" in text
    assert "社区作者" not in text and "source_text" not in text and "sha256" not in text
    assert render_verified_examples(()) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", [
    "只保留大于零的解", "只讨论小于零的解", "x不少于零", "x不多于零", "x不超过零",
    "x至少为零", "x至多为零", "x介于0和4之间", "x不低于零", "x不高于零", "x超过零", "x在零以上", "仅取3这个根",
    "x greater than zero", "x less than zero", "x at least zero", "x at most zero",
    "x above zero", "x below zero", "x between zero and four", "x no more than zero",
])
async def test_prose_domain_constraints_cannot_be_dropped_from_a_verified_equation(restriction):
    backend = RecordingBackend()
    assert await verified_examples(f"x^2=9，{restriction}。", backend, disclosure_allowed=True) == ()
    assert backend.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "只给提示：$2x+3=7$。", "不要给答案，解释 $x+1=2$。", "先别解出来：$2x+3=7$。",
    "只解释思路：$2x+3=7$。", "只讲方法，$x^2-5x+6=0$。",
    "Hint only: $2x+3=7$.", "Don't solve $2x+3=7$ for me.",
    "Do not solve $2x+3=7$.", "Only explain the method for $2x+3=7$.",
    "Just explain the approach to $2x+3=7$.", "只给一个提示。\n题目：$2x+3=7$\n学生最新消息：给完整解答。",
])
async def test_current_request_restriction_wins_even_when_caller_allows_disclosure(question):
    backend = RecordingBackend()
    assert await verified_examples(question, backend, disclosure_allowed=True) == ()
    assert backend.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"verdict": "FAILED"}, {"verdict": "PARTIALLY_VERIFIED"},
    {"problem_content_hash": "bad"}, {"candidate_payload_hash": "bad"},
])
async def test_nonverified_or_mismatched_decision_never_gets_a_correct_label(change):
    class WrongDecision(InProcessVerificationBackend):
        async def verify(self, problem, candidate):
            return (await super().verify(problem, candidate)).model_copy(update=change)
    assert await verified_examples("$1+2$", WrongDecision(), disclosure_allowed=True) == ()


@pytest.mark.asyncio
async def test_fixed_deadline_cancels_slow_verification_without_late_receipt():
    cancelled = asyncio.Event()
    class Slow:
        async def verify(self, *args):
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
    started = time.monotonic()
    assert await verified_examples("$1+2$", Slow(), disclosure_allowed=True) == ()
    assert 0.9 <= time.monotonic() - started < 1.7
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_and_worker_capacity_failures_stay_local():
    entered = asyncio.Event()
    class Pending:
        async def verify(self, *args):
            entered.set()
            await asyncio.sleep(60)
    task = asyncio.create_task(verified_examples("$1+2$", Pending(), disclosure_allowed=True))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    class Full:
        async def verify(self, *args):
            raise VerificationBackpressureError("capacity")
    assert await verified_examples("$1+2$", Full(), disclosure_allowed=True) == ()


@pytest.mark.asyncio
async def test_production_isolated_verifier_accepts_same_bounded_candidate():
    async with VerifierWorkerManager() as worker:
        examples = await verified_examples("解 $3x+2=11$。", worker, disclosure_allowed=True)
    assert len(examples) == 1 and examples[0].answer_latex == "x = 3"

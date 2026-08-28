"""Phase 3C LLMTutorWriter tests — fake provider, no real model/GPU.

Acceptance targets:
- the prompt carries ONLY the projected context (L1/L2/L3 never see the
  final answer; L5 sees the complete authorized solution);
- provider errors / timeouts / malformed output fall back to the template
  writer on the SAME projected input, with at most one model call (A3);
- raw candidates are returned as-is — TutorOutputGuard is the leakage gate;
- internal trace fields can never enter the prompt;
- the template path works with zero model environment.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import VerifiedSolutionRef
from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.disclosure import (
    DisclosedSolutionContext,
    SolutionDisclosureProjector,
)
from mathtutor.pedagogy.output_guard import TutorOutputGuard
from mathtutor.pedagogy.stage_policy import MIDDLE_POLICY
from mathtutor.pedagogy.tutor_writer import (
    LLMTutorWriter,
    PublicProblemView,
    TemplateTutorWriter,
)
from mathtutor.pedagogy.writer_settings import (
    MathTutorWriterSettings,
    load_math_tutor_writer_settings,
)
from mathtutor.solving import parse_problem, solve_problem, verify
from deeptutor.services.llm.exceptions import LLMAPIError

pytestmark = pytest.mark.asyncio

_SETTINGS = MathTutorWriterSettings(
    enabled=True, model="test-model", timeout_seconds=2.0, max_tokens=256
)

_LATEX = "x^{2} - 5x + 6 = 0"  # roots 2 and 3

# Disclosure hints deliberately free of the answer digits 2/3 so that the
# leakage assertions below can treat any 2/3 in the material as a leak.
_L1_HINT = "因式分解法：将多项式写成两个一次因式的乘积，每个因式对应一个根"
_L2_HINT = "先尝试因式分解，再分别解每个因式对应的方程"


def _verified_chain(text: str):
    """parse → solve → verify for one problem (helper style of test_pedagogy_chain)."""
    parsed = parse_problem(text).problem
    problem = MathProblem.canonicalize(
        problem_type=parsed.problem_type,
        normalized_ast=parsed.normalized_ast,
        display_latex=parsed.display_latex,
    )
    solved = solve_problem(problem, parsed)
    decision = verify(problem, solved.candidate)
    assert decision.verdict == "VERIFIED"
    ref = VerifiedSolutionRef(
        verification_log_id=decision.decision_id,
        problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash,
        solution_candidate_id=solved.candidate.candidate_id,
        solution_payload_hash=solved.candidate.payload_hash,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        attestation_hash="test",
    )
    return problem, solved.candidate, ref


class FakeLLMClient:
    """Injectable LLMClient stand-in recording every call (A3: call counts)."""

    def __init__(self, response: Any = "好的，请先说说你的思路。", exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, str | None, dict]] = []

    async def complete(self, prompt: str, system_prompt: str | None = None, **kwargs):
        self.calls.append((prompt, system_prompt, dict(kwargs)))
        if self.exc is not None:
            raise self.exc
        return self.response


def _prompts(fake: FakeLLMClient) -> tuple[str, str]:
    assert len(fake.calls) == 1
    user_prompt, system_prompt, _ = fake.calls[0]
    return user_prompt, system_prompt or ""


def _disclosure_material(user_prompt: str) -> str:
    """The portion of the user prompt after the disclosure header."""
    header = "已披露的教学内容（你唯一被允许使用的材料）："
    return user_prompt.split(header, 1)[1]


def _assert_no_answer_values(prompt: str, material: str) -> None:
    """The prompt/material must carry neither the final-answer field nor the
    answer values (roots 2, 3) — regardless of policy-budget digits in the
    system prompt, which are not solution content."""
    assert "final_answer" not in prompt
    for token in ("x=2", "x = 2", "x=3", "x = 3"):
        assert token not in prompt, token
    for digit in ("2", "3"):
        assert digit not in material, digit


def _l2_inputs(problem: MathProblem, *, action: TutorAction):
    projector = SolutionDisclosureProjector()
    disclosure = projector.project(None, None, action, strategy_hint=_L2_HINT)
    kwargs = dict(
        problem_view=PublicProblemView.of(problem),
        disclosure=disclosure,
        policy=MIDDLE_POLICY,
        action=action,
    )
    return kwargs


# ---------------------------------------------------------- prompt content


class TestPromptCarriesOnlyDisclosure:
    async def test_l1_prompt_has_no_final_answer(self) -> None:
        fake = FakeLLMClient()
        problem, _, _ = _verified_chain(f"x^2 - 5x + 6 = 0")
        projector = SolutionDisclosureProjector()
        action = TutorAction(
            action="EXPLAIN_CONCEPT", effective_assistance_level=1, solution_visibility="hint"
        )
        disclosure = projector.project(None, None, action, concept_hint=_L1_HINT)
        await LLMTutorWriter(client=fake, settings=_SETTINGS).write(
            problem_view=PublicProblemView.of(problem),
            disclosure=disclosure,
            policy=MIDDLE_POLICY,
            action=action,
        )
        user_prompt, _ = _prompts(fake)
        assert "概念提示" in user_prompt and "因式分解法" in user_prompt
        _assert_no_answer_values(user_prompt, _disclosure_material(user_prompt))

    async def test_l2_prompt_has_strategy_only(self) -> None:
        fake = FakeLLMClient()
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        await LLMTutorWriter(client=fake, settings=_SETTINGS).write(**_l2_inputs(problem, action=action))
        user_prompt, _ = _prompts(fake)
        assert f"策略提示：{_L2_HINT}" in user_prompt
        # No other disclosure material leaked in.
        assert "概念提示" not in user_prompt
        assert "已批准" not in user_prompt
        assert "完整解答" not in user_prompt
        _assert_no_answer_values(user_prompt, _disclosure_material(user_prompt))

    async def test_l3_prompt_has_approved_step_only(self) -> None:
        fake = FakeLLMClient()
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=3, solution_visibility="step"
        )
        disclosure = DisclosedSolutionContext(
            assistance_level=3,
            approved_step={
                "label": "先尝试因式分解",
                "hint": "把常数项拆成两个数的乘积，使它们的和等于一次项系数",
            },
        )
        await LLMTutorWriter(client=fake, settings=_SETTINGS).write(
            problem_view=PublicProblemView.of(problem),
            disclosure=disclosure,
            policy=MIDDLE_POLICY,
            action=action,
        )
        user_prompt, _ = _prompts(fake)
        assert "已批准的下一个步骤" in user_prompt
        assert "完整解答" not in user_prompt
        _assert_no_answer_values(user_prompt, _disclosure_material(user_prompt))

    async def test_l5_prompt_carries_full_solution(self) -> None:
        fake = FakeLLMClient()
        problem, candidate, ref = _verified_chain("x^2 - 5x + 6 = 0")
        projector = SolutionDisclosureProjector()
        action = TutorAction(
            action="SHOW_SOLUTION", effective_assistance_level=5, solution_visibility="full"
        )
        disclosure = projector.project(ref, candidate, action)
        out = await LLMTutorWriter(client=fake, settings=_SETTINGS).write(
            problem_view=PublicProblemView.of(problem),
            disclosure=disclosure,
            policy=MIDDLE_POLICY,
            action=action,
        )
        user_prompt, _ = _prompts(fake)
        assert "完整解答" in user_prompt
        assert "final_answer" in user_prompt  # L5 is the one level authorized to carry it
        assert "x = 2 或 x = 3" in user_prompt
        assert "计算判别式" in user_prompt
        assert out.writer_version == LLMTutorWriter.writer_version
        assert out.model_name == "test-model"
        assert out.text == fake.response  # returned exactly as produced

    async def test_system_prompt_reflects_stage_policy(self) -> None:
        fake = FakeLLMClient()
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        await LLMTutorWriter(client=fake, settings=_SETTINGS).write(**_l2_inputs(problem, action=action))
        _, system_prompt = _prompts(fake)
        assert "符号密度" in system_prompt and "可以适度使用数学符号" in system_prompt
        assert "证明严格度" in system_prompt
        assert str(MIDDLE_POLICY.max_response_chars) in system_prompt
        assert "不超过 3 个步骤" in system_prompt


# ------------------------------------------------------------- fallback (A3)


class TestFallback:
    async def test_provider_exception_falls_back_to_template(self) -> None:
        fake = FakeLLMClient(exc=LLMAPIError("local server down", provider="local"))
        writer = LLMTutorWriter(client=fake, settings=_SETTINGS)
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        kwargs = _l2_inputs(problem, action=action)
        out = await writer.write(**kwargs)
        expected = await TemplateTutorWriter().write(**kwargs)
        assert out == expected  # same input re-run through the template writer
        assert out.writer_version == TemplateTutorWriter.writer_version
        assert len(fake.calls) == 1  # A3: exactly one model call, no retry
        assert fake.calls[0][2]["max_retries"] == 0

    async def test_timeout_exception_falls_back_to_template(self) -> None:
        fake = FakeLLMClient(exc=TimeoutError("request timed out"))
        writer = LLMTutorWriter(client=fake, settings=_SETTINGS)
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        kwargs = _l2_inputs(problem, action=action)
        out = await writer.write(**kwargs)
        assert out == await TemplateTutorWriter().write(**kwargs)
        assert len(fake.calls) == 1

    async def test_slow_client_triggers_wait_for_timeout(self) -> None:
        class SlowClient(FakeLLMClient):
            async def complete(self, prompt, system_prompt=None, **kwargs):
                self.calls.append((prompt, system_prompt, dict(kwargs)))
                await asyncio.sleep(5)
                return "never returns"

        fake = SlowClient()
        settings = MathTutorWriterSettings(enabled=True, model="test-model", timeout_seconds=0.05)
        writer = LLMTutorWriter(client=fake, settings=settings)
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        kwargs = _l2_inputs(problem, action=action)
        out = await writer.write(**kwargs)
        assert out == await TemplateTutorWriter().write(**kwargs)
        assert len(fake.calls) == 1

    @pytest.mark.parametrize("bad", [None, "", "   ", "\n\t", 42])
    async def test_malformed_output_falls_back(self, bad: Any) -> None:
        fake = FakeLLMClient(response=bad)
        writer = LLMTutorWriter(client=fake, settings=_SETTINGS)
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        kwargs = _l2_inputs(problem, action=action)
        out = await writer.write(**kwargs)
        assert out == await TemplateTutorWriter().write(**kwargs)
        assert len(fake.calls) == 1


# ------------------------------------------------------- guard chain (INV4)


class TestGuardChain:
    async def test_malicious_output_returned_as_is_and_guard_catches(self) -> None:
        """The writer does NOT sanitize; TutorOutputGuard is the leakage gate."""
        problem, candidate, ref = _verified_chain("x^2 - 5x + 6 = 0")
        projector = SolutionDisclosureProjector()
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        disclosure = projector.project(None, None, action, strategy_hint=_L2_HINT)
        leaky = "这个知识点是因式分解，顺便告诉你 x=2 和 x=3。"
        fake = FakeLLMClient(response=leaky)
        out = await LLMTutorWriter(client=fake, settings=_SETTINGS).write(
            problem_view=PublicProblemView.of(problem),
            disclosure=disclosure,
            policy=MIDDLE_POLICY,
            action=action,
        )
        # INVARIANT 4: candidate text carries the leak verbatim.
        assert out.text == leaky
        assert out.writer_version == LLMTutorWriter.writer_version
        # The guard, given the verified solution, must intercept it.
        utterance = TutorOutputGuard().guard_or_fallback(
            candidate=out,
            candidate_solution=candidate,
            disclosure=disclosure,
            action=action,
        )
        assert utterance.fallback_used
        assert utterance.leak is not None


# ----------------------------------------------------- prompt hygiene (INV)


class TestNoInternalFieldsInPrompt:
    async def test_internal_trace_fields_never_enter_prompt(self) -> None:
        fake = FakeLLMClient()
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        await LLMTutorWriter(client=fake, settings=_SETTINGS).write(**_l2_inputs(problem, action=action))
        user_prompt, system_prompt = _prompts(fake)
        for forbidden in (
            "candidate_solution",
            "verification_log",
            "reasoning",
            "payload_hash",
            "verified_ref",
            "attestation",
            "candidate_id",
        ):
            assert forbidden not in user_prompt, forbidden
            assert forbidden not in system_prompt, forbidden


# ------------------------------------------------- no model environment (9)


class TestNoModelEnvironment:
    async def test_template_writer_needs_no_client(self) -> None:
        writer = TemplateTutorWriter()  # no client, no settings, no env
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        out = await writer.write(
            problem_view=PublicProblemView.of(problem),
            disclosure=DisclosedSolutionContext(assistance_level=2),
            policy=MIDDLE_POLICY,
            action=action,
        )
        assert out.text
        assert out.writer_version == TemplateTutorWriter.writer_version

    async def test_llm_writer_disabled_never_touches_client(self) -> None:
        # enabled=False (the shipped default): no client construction and no
        # model-layer import is needed — output is the template's verbatim.
        writer = LLMTutorWriter(settings=MathTutorWriterSettings(enabled=False))
        assert writer._client is None
        problem, _, _ = _verified_chain("x^2 - 5x + 6 = 0")
        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint"
        )
        kwargs = dict(
            problem_view=PublicProblemView.of(problem),
            disclosure=DisclosedSolutionContext(assistance_level=2),
            policy=MIDDLE_POLICY,
            action=action,
        )
        out = await writer.write(**kwargs)
        assert out == await TemplateTutorWriter().write(**kwargs)


# --------------------------------------------------------- settings loading


class TestWriterSettings:
    def test_load_settings_defaults_disabled(self, monkeypatch) -> None:
        for var in (
            "MATHTUTOR_WRITER_ENABLED",
            "MATHTUTOR_WRITER_MODEL",
            "MATHTUTOR_WRITER_TIMEOUT",
            "MATHTUTOR_WRITER_MAX_TOKENS",
        ):
            monkeypatch.delenv(var, raising=False)
        settings = load_math_tutor_writer_settings()
        assert settings.enabled is False  # fail-closed: template is the default
        assert settings.model == ""
        assert settings.timeout_seconds == 120.0
        assert settings.max_tokens == 1024

    def test_load_settings_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("MATHTUTOR_WRITER_ENABLED", "true")
        monkeypatch.setenv("MATHTUTOR_WRITER_MODEL", " qwen-tutor ")
        monkeypatch.setenv("MATHTUTOR_WRITER_TIMEOUT", "30")
        monkeypatch.setenv("MATHTUTOR_WRITER_MAX_TOKENS", "512")
        settings = load_math_tutor_writer_settings()
        assert settings.enabled is True
        assert settings.model == "qwen-tutor"
        assert settings.timeout_seconds == 30.0
        assert settings.max_tokens == 512

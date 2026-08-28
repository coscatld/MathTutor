"""TutorWriter — natural-language realization of a projected context (Phase 3C).

The ONLY place an LLM may express tutoring language. It receives the
DisclosedSolutionContext — never the full solution unless the projector
granted L5 — plus the public problem view and the chosen action.

MVP ships the deterministic :class:`TemplateTutorWriter` (no model call;
offline-safe, fully tested). :class:`LLMTutorWriter` is the drop-in slot for
the local model gateway (vLLM / Ollama / OpenAI-compatible endpoint) through
DeepTutor's existing model provider — no new agent framework.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
from mathtutor.pedagogy.stage_policy import StagePolicy
from mathtutor.pedagogy.writer_settings import (
    MathTutorWriterSettings,
    load_math_tutor_writer_settings,
)

class CompletionClient(Protocol):
    """Small structural boundary required by :class:`LLMTutorWriter`."""

    async def complete(self, *args: Any, **kwargs: Any) -> Any: ...


class PublicProblemView(BaseModel):
    """The student-visible problem surface: statement, no solution fields."""

    model_config = ConfigDict(frozen=True)

    problem_type: str
    display_latex: str

    @classmethod
    def of(cls, problem: MathProblem) -> "PublicProblemView":
        return cls(
            problem_type=problem.problem_type,
            display_latex=problem.display_latex,
        )


class TutorWriterCandidate(BaseModel):
    """Raw writer output BEFORE the guard — never student-facing directly."""

    model_config = ConfigDict(frozen=True)

    text: str
    writer_version: str
    model_name: str = ""


class TutorWriter(Protocol):
    async def write(
        self,
        *,
        problem_view: PublicProblemView,
        disclosure: DisclosedSolutionContext,
        policy: StagePolicy,
        action: TutorAction,
    ) -> TutorWriterCandidate: ...


_TEMPLATES = {
    0: {
        "GIVE_HINT": "先自己想一想，把你能写的步骤写下来，我会帮你检查。",
        "EXPLAIN_CONCEPT": "我们可以先回顾一下相关的知识点，再回到这道题。",
        "ASK_STUDENT": "请把你的思路或答案发给我。",
    },
    1: {
        "EXPLAIN_CONCEPT": "先回忆一下这个知识点的定义，再看看题目中哪些条件可以用上。",
        "GIVE_HINT": "先回忆一下这个知识点的定义，再看看题目中哪些条件可以使用。",
    },
    2: {
        "GIVE_HINT": "先确定应该使用哪一种解题方法，再进行具体计算。",
        "SHOW_EXAMPLE": "我可以给你看一个同类型的简单例子，先理解方法本身。",
        "EXPLAIN_CONCEPT": "这个方法的关键是理解它每一步的依据。",
    },
    3: {
        "GIVE_HINT": "先完成当前这一小步，再把结果发给我。",
        "CORRECT_STEP": "这一步有点问题，先检查你刚才的这一步。",
    },
    4: {"GIVE_HINT": "你目前做的前几步是对的，继续沿着这个方向走。"},
    5: {"SHOW_SOLUTION": "这是完整的解答过程，请对照自己的思路检查。"},
}


class TemplateTutorWriter:
    """Deterministic writer over the projected context (MVP, no model call).

    Templates embed NO solution content for L0-L4 — the projector is the
    only gate. L5 is the one exception: the projector has explicitly
    authorized the full solution, so the template RENDERS it (otherwise the
    student would receive a placeholder instead of the permitted answer).
    """

    writer_version = "mt-template-v1"

    async def write(
        self,
        *,
        problem_view: PublicProblemView,
        disclosure: DisclosedSolutionContext,
        policy: StagePolicy,
        action: TutorAction,
    ) -> TutorWriterCandidate:
        if disclosure.assistance_level == 5 and disclosure.full_solution is not None:
            text = _render_full_solution(disclosure.full_solution)
            return TutorWriterCandidate(text=text, writer_version=self.writer_version)
        level_templates = _TEMPLATES.get(disclosure.assistance_level, {})
        text = level_templates.get(action.action)
        if text is None:
            text = level_templates.get("GIVE_HINT") or _TEMPLATES[0]["ASK_STUDENT"]
        return TutorWriterCandidate(text=text, writer_version=self.writer_version)


def _render_full_solution(full_solution: dict) -> str:
    """Render the display-only L5 projection; never stringify raw payloads."""
    parts: list[str] = ["完整解答："]
    steps = full_solution.get("steps") or []
    for step in steps:
        if isinstance(step, dict):
            text = str(step.get("display_text") or "继续按已验证的步骤计算。")
            latex = str(step.get("display_latex") or "")
            parts.append(f"{text}：{latex}" if latex else text)
        else:
            parts.append("继续按已验证的步骤计算。")
    answer = full_solution.get("final_answer") or {}
    if isinstance(answer, dict):
        latex = answer.get("display_latex")
        if latex:
            parts.append(f"答案：{latex}")
        else:
            parts.append("答案已在上述计算中得出。")
    else:
        parts.append("答案已在上述计算中得出。")
    return "\n".join(parts)


logger = logging.getLogger(__name__)

# Deterministic teaching temperature: tutoring language should be stable.
_TEMPERATURE = 0.4

_ACTION_INTENT = {
    "ASK_STUDENT": "请学生展示自己的思路",
    "GIVE_HINT": "给学生一个渐进式的提示",
    "EXPLAIN_CONCEPT": "向学生解释相关概念或知识点",
    "SHOW_EXAMPLE": "给学生展示一个同类型示例",
    "CORRECT_STEP": "指出并纠正学生当前步骤的问题",
    "REQUEST_RETRY": "请学生重新尝试上一步",
    "SHOW_SOLUTION": "向学生展示完整解答过程",
    "GENERATE_PRACTICE": "为学生生成一道练习题",
}

_SYMBOL_DENSITY_RULES = {
    "low": "尽量少用数学符号，多用自然语言描述",
    "medium": "可以适度使用数学符号，并配合自然语言解释",
    "high": "可以使用完整的符号化推导",
}

_PROOF_RIGOR_RULES = {
    "none": "不要求给出严格证明",
    "basic": "关键步骤给出基本依据",
    "strict": "每一步都必须给出严格依据",
}


def _build_system_prompt(policy: StagePolicy) -> str:
    """Expression constraints from the StagePolicy — hard policy, no solution content."""
    density = _SYMBOL_DENSITY_RULES.get(policy.symbol_density, _SYMBOL_DENSITY_RULES["medium"])
    rigor = _PROOF_RIGOR_RULES.get(policy.proof_rigor, _PROOF_RIGOR_RULES["basic"])
    scale = (
        "单个步骤或单个动作"
        if policy.max_steps_per_turn <= 1
        else f"不超过 {policy.max_steps_per_turn} 个步骤"
    )
    return (
        "你是一名面向 K12 学生的数学辅导老师，负责把服务器允许披露的教学材料"
        "表达成对学生的辅导语言。\n"
        "硬性规则：你只能使用对话中给出的【已披露的教学内容】；"
        "任何未披露的解题步骤、中间结果或最终答案都绝对不允许出现在你的回复里；"
        "如果披露的材料不足以推进，就引导学生自己思考，而不是替他们补全。\n"
        "表达要求（来自当前学段的教学策略）：\n"
        f"- 符号密度：{density}\n"
        f"- 证明严格度：{rigor}\n"
        f"- 回复长度不超过 {policy.max_response_chars} 个字符\n"
        f"- 本轮内容规模：{scale}\n"
        f"- 允许一题多解：{'是' if policy.allow_multi_method else '否'}\n"
        f"- 允许先给出公式再解释：{'是' if policy.allow_formula_first else '否'}\n"
        f"- 优先用具体数字和例子表达：{'是' if policy.prefer_concrete_representation else '否'}\n"
        "请用中文回复，直接输出要对学生说的话，不要包含任何前言、解释或标注。"
    )


def _disclosure_material(disclosure: DisclosedSolutionContext) -> str:
    """Serialize ONLY the disclosed fields; levels without material say so."""
    parts: list[str] = []
    if disclosure.concept_hint:
        parts.append(f"概念提示：{disclosure.concept_hint}")
    if disclosure.strategy_hint:
        parts.append(f"策略提示：{disclosure.strategy_hint}")
    if disclosure.approved_step is not None:
        parts.append(
            "已批准的下一个步骤："
            + json.dumps(disclosure.approved_step, ensure_ascii=False, default=str)
        )
    if disclosure.approved_prefix:
        parts.append(
            "已批准的前置步骤："
            + json.dumps(list(disclosure.approved_prefix), ensure_ascii=False, default=str)
        )
    if disclosure.full_solution is not None:
        parts.append(
            "完整解答（已获授权向学生展示）："
            + json.dumps(disclosure.full_solution, ensure_ascii=False, default=str)
        )
    if not parts:
        parts.append("（本轮没有披露任何解题材料）")
    return "\n".join(parts)


def _build_user_prompt(
    problem_view: PublicProblemView,
    disclosure: DisclosedSolutionContext,
    action: TutorAction,
) -> str:
    """User prompt carries ONLY the problem surface, the action intent and the disclosure."""
    intent = _ACTION_INTENT.get(action.action, action.action)
    return "\n".join(
        (
            f"题目：{problem_view.display_latex}",
            (
                f"本轮动作：{action.action}（{intent}），帮助级别 L{disclosure.assistance_level}，"
                f"可见内容：{action.solution_visibility}"
            ),
            "已披露的教学内容（你唯一被允许使用的材料）：",
            _disclosure_material(disclosure),
        )
    )


class LLMTutorWriter:
    """Local-model realization of the TutorWriter role (Phase 3C second pass).

    Receives ONLY the projected context (INVARIANT 2/3): the signature is
    exactly ``PublicProblemView + DisclosedSolutionContext + StagePolicy +
    TutorAction`` — the model can never see content outside the disclosure.

    Failure posture (A3): the model layer is called at most once per
    ``write()``. Provider errors, timeouts, or malformed output fall back to
    the deterministic :class:`TemplateTutorWriter` on the SAME projected
    input — never an exception out of the pedagogy chain. Leakage
    interception is NOT this class's job: the raw candidate is returned
    as-is (INVARIANT 4) and :class:`TutorOutputGuard` runs afterwards.
    """

    writer_version = "mt-llm-v1"

    def __init__(
        self,
        client: CompletionClient | None = None,
        settings: MathTutorWriterSettings | None = None,
        fallback: TutorWriter | None = None,
        model_name: str = "",
    ) -> None:
        """``client`` is injectable (the gateway's ``GatewayRoleClient`` in
        the product, fakes in tests); when None the writer deterministically
        falls back to :class:`TemplateTutorWriter` — there is deliberately
        NO self-provisioning path to the legacy DeepTutor LLM layer (the
        gateway is the only generative surface; see
        ``gateway_config.build_tutor_writer``). ``fallback`` defaults to
        :class:`TemplateTutorWriter`."""
        self._client = client
        self._settings = settings if settings is not None else load_math_tutor_writer_settings()
        self._fallback = fallback if fallback is not None else TemplateTutorWriter()
        # Legacy attribute from the Phase 3C stub; kept for introspection.
        self.model_name = model_name or self._settings.model

    def _resolve_client(self) -> CompletionClient | None:
        """Return the injected client, or None → deterministic template.

        The gateway is the ONLY source of model clients
        (``gateway_config.build_tutor_writer`` injects a
        ``GatewayRoleClient``); a writer without an injected client never
        provisions its own model access. None is also the disabled case —
        the caller converts it into a template fallback.
        """
        return self._client

    def _model_name(self) -> str:
        if self._settings.model:
            return self._settings.model
        return getattr(getattr(self._client, "config", None), "model", "") or self.model_name

    async def write(
        self,
        *,
        problem_view: PublicProblemView,
        disclosure: DisclosedSolutionContext,
        policy: StagePolicy,
        action: TutorAction,
    ) -> TutorWriterCandidate:
        try:
            client = self._resolve_client()
        except Exception:
            logger.warning(
                "LLMTutorWriter: LLM client unavailable — template fallback", exc_info=True
            )
            return await self._fallback_candidate(
                problem_view=problem_view,
                disclosure=disclosure,
                policy=policy,
                action=action,
            )
        if client is None:
            # Disabled (or not provisioned): deterministic path, no model call.
            return await self._fallback_candidate(
                problem_view=problem_view,
                disclosure=disclosure,
                policy=policy,
                action=action,
            )

        system_prompt = _build_system_prompt(policy)
        user_prompt = _build_user_prompt(problem_view, disclosure, action)
        try:
            raw = await asyncio.wait_for(
                client.complete(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=_TEMPERATURE,
                    max_tokens=self._settings.max_tokens,
                    max_retries=0,  # A3: exactly one provider attempt.
                ),
                timeout=self._settings.timeout_seconds,
            )
        except Exception:
            logger.warning("LLMTutorWriter: model call failed — template fallback", exc_info=True)
            return await self._fallback_candidate(
                problem_view=problem_view,
                disclosure=disclosure,
                policy=policy,
                action=action,
            )

        if not isinstance(raw, str) or not raw.strip():
            logger.warning("LLMTutorWriter: malformed model output — template fallback")
            return await self._fallback_candidate(
                problem_view=problem_view,
                disclosure=disclosure,
                policy=policy,
                action=action,
            )

        # INVARIANT 4: return the candidate exactly as produced — no
        # sanitizing here; TutorOutputGuard is the only leakage gate.
        return TutorWriterCandidate(
            text=raw,
            writer_version=self.writer_version,
            model_name=self._model_name(),
        )

    async def _fallback_candidate(
        self,
        *,
        problem_view: PublicProblemView,
        disclosure: DisclosedSolutionContext,
        policy: StagePolicy,
        action: TutorAction,
    ) -> TutorWriterCandidate:
        """Deterministic fallback on the SAME projected input (A3)."""
        try:
            return await self._fallback.write(
                problem_view=problem_view,
                disclosure=disclosure,
                policy=policy,
                action=action,
            )
        except Exception:
            # The pedagogy chain must never die because of a writer.
            logger.exception("LLMTutorWriter: fallback writer failed")
            return TutorWriterCandidate(
                text=_TEMPLATES[0]["ASK_STUDENT"],
                writer_version=TemplateTutorWriter.writer_version,
            )


__all__ = [
    "LLMTutorWriter",
    "PublicProblemView",
    "TemplateTutorWriter",
    "TutorWriter",
    "TutorWriterCandidate",
]

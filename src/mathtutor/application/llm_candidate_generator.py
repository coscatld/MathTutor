"""Practice candidate generators — deterministic fallback chain (Phase 5 §7.4).

The generator chain is fixed:

    bank (curated seed items) > template (per-family patterns) > LLM
    (gateway role PRACTICE_GENERATOR, LAST RESORT — fail closed)

Every candidate is UNVERIFIED by construction; ``source_type`` is only a
claim attached to the exercise by the release service (BANK/TEMPLATE/LLM),
never a trust grant — all three sources pass the IDENTICAL release gate
(Parser → Solver → Verifier → Release Attestation) before any offer exists.

The LLM generator prompt is built ONLY from :class:`PracticeGenerationContext`
public fields — never mastery internals, answer keys, candidate solutions or
repository rows. The LLM never judges, verifies or issues anything.
"""

from __future__ import annotations

import json
from typing import Sequence
from uuid import UUID

from mathtutor.application.adaptive_practice import (
    CandidateExercise,
    CandidateExerciseGenerator,
)
from mathtutor.application.practice_release import SEED_BANK
from mathtutor.domain.hashing import to_json_safe
from mathtutor.domain.practice_context import PracticeGenerationContext
from mathtutor.infrastructure.generative_gateway import (
    GatewayRoleClient,
    GenerativeModelGateway,
    ModelRole,
)
from mathtutor.learning.skills import (
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
    SKILL_POLYNOMIAL_BASIC,
    SKILL_QUADRATIC_EQUATION,
)

# ---------------------------------------------------------------------------
# Errors + source mapping
# ---------------------------------------------------------------------------


class PracticeGenerationError(Exception):
    """Candidate generation failed (fail closed — no candidates)."""


def source_type_for_generated_by(generated_by: str) -> str:
    """Map the generator claim to the exercise source_type (BANK/TEMPLATE/LLM).

    A claim, never a trust grant: the release gate applies identically to
    every source type.
    """
    if generated_by.startswith("mt-llm-"):
        return "LLM"
    if generated_by.startswith("mt-template-"):
        return "TEMPLATE"
    if generated_by.startswith("mt-bank-"):
        return "BANK"
    return "BANK"  # unknown/mock generators: deterministic default


# ---------------------------------------------------------------------------
# Template generator (deterministic, per family)
# ---------------------------------------------------------------------------

_FAMILY_FOR_SKILL: dict[str, str] = {
    SKILL_ARITHMETIC: "arithmetic",
    SKILL_POLYNOMIAL_BASIC: "polynomial",
    SKILL_LINEAR_EQUATION: "linear",
    SKILL_QUADRATIC_EQUATION: "quadratic",
}

# Curated statement patterns — every string must parse AND verify through the
# full release gate (the seed bank + tests enforce this continuously).
_TEMPLATES: dict[str, tuple[str, ...]] = {
    "arithmetic": ("3/4 + 1/2", "7/8 - 1/4", "1/2 + 1/3", "2/3 + 1/6"),
    "polynomial": ("(x + 1)^2", "2(x + 1) + 3", "(x + 2)^2", "3(x + 2) + 1"),
    "linear": ("2x + 3 = 7", "3x - 5 = 4", "2x + 1 = 5", "4x + 3 = 15"),
    "quadratic": (
        "x^2 - 5x + 6 = 0",
        "x^2 - 4x + 4 = 0",
        "x^2 - 3x + 2 = 0",
        "x^2 - 7x + 12 = 0",
    ),
}


def _family_for_targets(context: PracticeGenerationContext) -> str | None:
    """Exactly one family from the target skill ids, else None (ambiguous)."""
    families = {
        _FAMILY_FOR_SKILL[skill_id]
        for skill_id in context.target_skill_ids
        if skill_id in _FAMILY_FOR_SKILL
    }
    if len(families) != 1:
        return None
    return next(iter(families))


class TemplateCandidateExerciseGenerator:
    """Deterministic per-family statement generator (source: TEMPLATE).

    Identical contexts → identical statements (tests rely on it); the
    release gate still verifies every statement independently.
    """

    generated_by = "mt-template-candidate-v1"

    async def generate(
        self, context: PracticeGenerationContext, *, count: int = 1
    ) -> list[CandidateExercise]:
        family = _family_for_targets(context)
        if family is None:
            return []
        options = _TEMPLATES.get(family, ())
        if not options:
            return []
        seed = "".join(context.target_skill_ids)
        if has_usable_document_context(context):
            # Document text participates in which isomorphic template is
            # chosen — the chain does not ignore a successful recall.
            seed += "|" + "".join(chunk.text for chunk in context.document_context.chunks)
        index = sum(ord(ch) for ch in seed) % len(options)
        candidates: list[CandidateExercise] = []
        for offset in range(max(1, count)):
            statement = options[(index + offset) % len(options)]
            candidates.append(
                CandidateExercise(
                    student_id=context.student_id,
                    problem_statement=statement,
                    skill_ids=context.target_skill_ids,
                    concept_ids=context.target_concept_ids,
                    difficulty=context.desired_difficulty,
                    generated_by=(
                        "mt-template-document-grounded-v1"
                        if has_usable_document_context(context)
                        else self.generated_by
                    ),
                    context_version=context.context_version,
                    provenance=context.provenance,
                )
            )
        return candidates


# ---------------------------------------------------------------------------
# LLM generator (gateway role PRACTICE_GENERATOR — last resort, fail closed)
# ---------------------------------------------------------------------------


_LLM_SYSTEM_PROMPT = (
    "你是 K12 数学练习题生成器。只输出一个 JSON 字符串数组，"
    "每项是一道题的纯文本（分数运算 / 多项式化简 / 一元一次方程 / 一元二次方程，"
    "使用数学标准写法，如 2x + 3 = 7、x^2 - 5x + 6 = 0）。"
    "如果提供了 document_context（学生自己的资料摘录），必须根据资料出同构题："
    "同一知识点、不同数字，不要忽略资料，也不要照抄整段课文。"
    "不要输出任何解释、答案或解题过程。"
)

# When at least this many projected chunks are present, the chain must
# consume document_context instead of returning an unconstrained bank item.
DOCUMENT_HIT_THRESHOLD = 1


def build_llm_prompt(context: PracticeGenerationContext) -> str:
    """Prompt from PracticeGenerationContext PUBLIC fields only (§7.4).

    ``student_id``/``context_version``/``provenance`` are routing metadata,
    not generation input — they never reach the model. Nothing else is
    included: no mastery internals, no answer keys, no repository rows.
    """
    public = {
        "target_skill_ids": list(context.target_skill_ids),
        "target_concept_ids": list(context.target_concept_ids),
        "current_mastery": [
            {"skill_id": entry.skill_id, "mastery": entry.mastery}
            for entry in context.current_mastery
        ],
        "active_misconceptions": [
            {"rule_id": entry.rule_id, "confidence": entry.confidence}
            for entry in context.active_misconceptions
        ],
        "recent_error_patterns": [
            {"rule_id": entry.rule_id, "occurrence_count": entry.occurrence_count}
            for entry in context.recent_error_patterns
        ],
        "recent_attempt_summary": [
            {
                "skill_id": entry.skill_id,
                "correctness": entry.correctness,
                "effective_assistance_level": entry.effective_assistance_level,
                "attempt_index": entry.attempt_index,
            }
            for entry in context.recent_attempt_summary
        ],
        "desired_difficulty": context.desired_difficulty,
    }
    if context.personal_preferences is not None:
        public["personal_preferences"] = to_json_safe(
            context.personal_preferences.model_dump()
        )
    if context.document_context is not None:
        public["document_context"] = _document_context_public(context.document_context)
    return json.dumps(public, ensure_ascii=False, sort_keys=True)


def _document_context_public(selection) -> dict:
    """Citation-ready projection: filename, page, chunk sequence, score, text."""
    return {
        "document_id": str(selection.document_id),
        "filename": selection.filename,
        "chunks": [
            {
                "filename": chunk.filename or selection.filename,
                "page": chunk.page,
                "sequence": chunk.sequence,
                "score": chunk.score,
                "text": chunk.text,
            }
            for chunk in selection.chunks
        ],
    }


def has_usable_document_context(context: PracticeGenerationContext) -> bool:
    selection = context.document_context
    return selection is not None and len(selection.chunks) >= DOCUMENT_HIT_THRESHOLD


def _parse_llm_statements(text: str) -> list[str]:
    """Parse the model's output into statements (JSON array, else lines)."""
    text = (text or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [line.strip() for line in text.splitlines() if line.strip()]


class LLMCandidateExerciseGenerator:
    """LLM-backed candidate generator — LAST resort in the fallback chain.

    Fail closed: an unconfigured gateway (``client_for`` → None) or any
    generation error raises :class:`PracticeGenerationError`; the caller
    (chain / service) falls back to deterministic sources or produces no
    offer. The model's output is STILL just a statement string — the
    Parser → Solver → Verifier → Release gate decides whether it may ever
    reach a student.
    """

    generated_by = "mt-llm-candidate-v1"

    def __init__(
        self,
        gateway: GenerativeModelGateway | None = None,
        *,
        client: GatewayRoleClient | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        elif gateway is not None:
            self._client = gateway.client_for(ModelRole.PRACTICE_GENERATOR)
        else:
            self._client = None

    async def generate(
        self, context: PracticeGenerationContext, *, count: int = 1
    ) -> list[CandidateExercise]:
        if self._client is None:
            raise PracticeGenerationError("PRACTICE_GENERATOR 网关未配置（fail closed）")
        try:
            text = await self._client.complete(
                prompt=build_llm_prompt(context),
                system_prompt=_LLM_SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=256,
                max_retries=1,
            )
        except Exception as exc:  # GenerativeConfigError / provider failures
            raise PracticeGenerationError(f"LLM 生成失败: {exc}") from exc
        statements = _parse_llm_statements(text)[:max(1, count)]
        if not statements:
            raise PracticeGenerationError("LLM 输出无法解析为题目")
        return [
            CandidateExercise(
                student_id=context.student_id,
                problem_statement=statement,
                skill_ids=context.target_skill_ids,
                concept_ids=context.target_concept_ids,
                difficulty=context.desired_difficulty,
                generated_by=self.generated_by,
                context_version=context.context_version,
                provenance=context.provenance,
            )
            for statement in statements
        ]


# ---------------------------------------------------------------------------
# Deterministic fallback chain: bank > template > LLM (§7.4)
# ---------------------------------------------------------------------------


def bank_candidates_for(
    context: PracticeGenerationContext, *, count: int = 1
) -> list[CandidateExercise]:
    """Curated seed items matching the targets (source: BANK)."""
    wanted_skills = set(context.target_skill_ids) or None
    wanted_concepts = set(context.target_concept_ids) or None
    matches: list[CandidateExercise] = []
    for item in SEED_BANK:
        if wanted_skills and not (set(item.skill_ids) & wanted_skills):
            continue
        if wanted_concepts and not (set(item.concept_ids) & wanted_concepts):
            continue
        matches.append(
            CandidateExercise(
                student_id=context.student_id,
                problem_statement=item.problem_statement,
                skill_ids=item.skill_ids,
                concept_ids=item.concept_ids,
                difficulty=item.difficulty,
                generated_by="mt-bank-seed-v1",
                context_version=context.context_version,
                provenance=context.provenance,
            )
        )
        if len(matches) >= max(1, count):
            break
    return matches


class PracticeGeneratorChain:
    """bank > template > LLM — deterministic sources first, LLM last resort.

    ``generated_by`` marks each candidate's source; the release service
    derives ``source_type`` from it (a claim, never a trust grant).
    """

    generated_by = "mt-practice-chain-v1"

    def __init__(
        self,
        *,
        gateway: GenerativeModelGateway | None = None,
        template: CandidateExerciseGenerator | None = None,
    ) -> None:
        self._gateway = gateway
        self._template = template or TemplateCandidateExerciseGenerator()

    async def generate(
        self, context: PracticeGenerationContext, *, count: int = 1
    ) -> list[CandidateExercise]:
        if has_usable_document_context(context):
            return await self._generate_from_documents(context, count=count)
        return await self._generate_without_documents(context, count=count)

    async def _generate_without_documents(
        self, context: PracticeGenerationContext, *, count: int
    ) -> list[CandidateExercise]:
        # bank > template > LLM when no user-document hits.
        bank = bank_candidates_for(context, count=count)
        if bank:
            return bank
        template_candidates = await self._template.generate(context, count=count)
        if template_candidates:
            return template_candidates
        return await self._try_llm(context, count=count)

    async def _generate_from_documents(
        self, context: PracticeGenerationContext, *, count: int
    ) -> list[CandidateExercise]:
        """Hits above threshold: consume document_context, do not drop recall.

        LLM reads the projected chunks. If the gateway is off, the
        document-grounded template still uses the chunk text as the seed.
        Bank is last — unconstrained bank would silently ignore the notes.
        """
        llm_candidates = await self._try_llm(context, count=count)
        if llm_candidates:
            return llm_candidates
        template_candidates = await self._template.generate(context, count=count)
        if template_candidates:
            return template_candidates
        return bank_candidates_for(context, count=count)

    async def _try_llm(
        self, context: PracticeGenerationContext, *, count: int
    ) -> list[CandidateExercise]:
        if self._gateway is None:
            return []
        llm = LLMCandidateExerciseGenerator(self._gateway)
        try:
            return await llm.generate(context, count=count)
        except PracticeGenerationError:
            return []


__all__ = [
    "LLMCandidateExerciseGenerator",
    "PracticeGenerationError",
    "PracticeGeneratorChain",
    "TemplateCandidateExerciseGenerator",
    "DOCUMENT_HIT_THRESHOLD",
    "bank_candidates_for",
    "build_llm_prompt",
    "has_usable_document_context",
    "source_type_for_generated_by",
]

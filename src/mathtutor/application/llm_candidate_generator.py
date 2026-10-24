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
from mathtutor.domain.practice_recommendation import MaterialDesignBasis
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
    SKILL_LINEAR_SYSTEM,
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
    SKILL_LINEAR_SYSTEM: "linear_system",
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


def candidate_is_distinct(statement: str, excluded: Sequence[str]) -> bool:
    """Exclude canonical repeats and answer-copy variants, not just text duplicates."""
    from mathtutor.solving.parser import parse_problem
    from mathtutor.solving.solver import solve_problem
    from mathtutor.domain.problem import MathProblem
    from mathtutor.domain.hashing import content_hash

    def identities(text):
        outcome = parse_problem(text)
        if outcome.kind != "parsed" or outcome.problem is None:
            return None
        parsed = outcome.problem
        problem = MathProblem.canonicalize(problem_type=parsed.problem_type,
            normalized_ast=parsed.normalized_ast, display_latex=parsed.display_latex)
        solved = solve_problem(problem, parsed)
        answer = content_hash(solved.candidate.final_answer) if solved.candidate is not None else None
        return problem.content_hash, problem.problem_type, answer

    identity = identities(statement)
    if identity is None:
        return True  # Actual parse failure belongs to the release gate.
    for old in excluded:
        previous = identities(old)
        if previous and (identity[0] == previous[0] or (identity[1] == previous[1] and identity[2] is not None and identity[2] == previous[2])):
            return False
    return True


def candidate_problem_revision(statement: str) -> str | None:
    """Use the release gate's canonical identity without solving past history."""
    from mathtutor.solving.parser import parse_problem
    from mathtutor.domain.problem import MathProblem
    outcome = parse_problem(statement)
    if outcome.kind != "parsed" or outcome.problem is None:
        return None  # Invalid candidates still fail the full release gate.
    parsed = outcome.problem
    return MathProblem.canonicalize(problem_type=parsed.problem_type,
        normalized_ast=parsed.normalized_ast, display_latex=parsed.display_latex).content_hash


def _candidate_allowed(statement: str, context: PracticeGenerationContext) -> bool:
    return (candidate_problem_revision(statement) not in context.excluded_problem_revisions
            and candidate_is_distinct(statement, context.excluded_problem_statements))


def _parameterized_templates(family: str, difficulty: int) -> tuple[str, ...]:
    """Finite verifier-covered pool; difficulty affects the mathematical structure."""
    result = []
    for n in range(2, 14):
        a, b, root = n + 1, n, n + 4
        if family == "linear":
            if difficulty == 1:
                text = f"x + {b} = {root + b}"
            elif difficulty == 2:
                text = f"{a}x - {b} = {a * root - b}"
            elif difficulty == 3:
                text = f"{a + 1}x - {b} = x + {a * root - b}"
            elif difficulty == 4:
                text = f"x/{a} - {b} = {root}"
            else:
                text = f"({a}x - {b})/2 = {a * root - b}/2"
        elif family == "arithmetic":
            text = f"{a} + {b} * 2" if difficulty == 1 else f"{b}/{a} + {n + difficulty}/{n + difficulty + 2}"
        elif family == "polynomial":
            text = f"{a}x + {b}x" if difficulty == 1 else f"{max(1, difficulty - 1)}(x + {b})^2 + {a}x"
        elif family == "linear_system":
            second = n + 2
            if difficulty <= 2:
                text = f"x+y={root + second}; x-y={root - second}"
            else:
                text = f"{a}x+y={a * root + second}; x-{difficulty}y={root - difficulty * second}"
        else:
            second = root + max(1, difficulty - 1)
            text = f"x^2 - {root + second}x + {root * second} = 0"
        result.append(text)
    return tuple(result)


def _document_basis(context: PracticeGenerationContext, family: str) -> MaterialDesignBasis | None:
    """Use a precise skill/method quote only when it changes a template feature."""
    if context.document_context is None:
        return None
    methods = {
        "linear": (("移项", "使用含减法常数项的方程，练习移项与符号保持"),),
        "arithmetic": (("通分", "使用不同分母的分数加法，练习通分"), ("分数", "使用不同分母的分数加法，练习通分")),
        "polynomial": (("乘法公式", "使用二项式平方展开，练习乘法公式"), ("展开", "使用二项式平方展开，练习展开")),
        "quadratic": (("因式分解", "使用两个整数根的二次方程，练习因式分解"),),
        "linear_system": (("消元", "使用两个一次方程，通过线性组合消去一个未知数"),),
    }
    for chunk in context.document_context.chunks:
        for term, influence in methods.get(family, ()):
            start = chunk.text.find(term)
            if start >= 0:
                return MaterialDesignBasis(source_chunk_id=chunk.chunk_id,
                    skill_id=context.target_skill_ids[0], quote_start=start,
                    quote_end=start + len(term), quote=term, design_influence=influence)
    return None


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
        basis = _document_basis(context, family)
        # A method quote constrains actual structure; difficulty 1 can't claim
        # fractional/square-method grounding that the generated item omits.
        if context.desired_difficulty == 1 and family in {"arithmetic", "polynomial", "linear"}:
            basis = None
        options = _parameterized_templates(family, context.desired_difficulty)
        if context.practice_purpose != "C" and context.foundation_focus:
            # A verified error selects actual task structure, not merely a
            # sentence in an LLM prompt. These still pass the full release gate.
            if family == "linear" and context.foundation_focus == "equality_preservation":
                difficulty = context.desired_difficulty
                options = tuple(
                    f"x+{n}={3 * n + 1}" if difficulty == 1 else
                    f"2x+{n}=x+{3 * n + 1}" if difficulty == 2 else
                    f"2(x+{n})=x+{3 * n + 1}" if difficulty == 3 else
                    f"(2x+{n})/3=x-({n + 1})" if difficulty == 4 else
                    f"(2x+{n})/3=(x-({n + 1}))/2"
                    for n in range(2, 14))
                basis = None
            elif family == "linear" and context.foundation_focus == "signed_operations":
                difficulty = context.desired_difficulty
                options = tuple(
                    f"-x={n}" if difficulty == 1 else
                    f"-2x+{n}={3 * n}" if difficulty == 2 else
                    f"-2(x+{n})={3 * n}-x" if difficulty == 3 else
                    f"-2(x+{n})/3={n}-x" if difficulty == 4 else
                    f"-2(x+{n})/3=({n}-x)/2"
                    for n in range(2, 14))
                basis = None
            elif family == "arithmetic" and context.foundation_focus == "signed_operations":
                options = tuple(f"-{n}-(-{n + 3})*2" for n in range(2, 14))
                basis = None
        if context.practice_purpose == "C":
            # A broad family is not enough to justify an unrelated seed item.
            # Foundation items exercise the diagnosed prerequisite operation.
            if family == "arithmetic":
                if context.foundation_focus == "fraction_operations":
                    options = tuple(f"{n}/3 + 1/2" for n in range(2, 14))
                else:
                    options = tuple(f"{n} - (-{n + 3})" for n in range(2, 14))
                    basis = None
            elif family == "linear":
                options = tuple(f"x + {n} = {3 * n + 1}" for n in range(2, 14))
                basis = None
            elif family == "polynomial":
                options = tuple(f"{n}(x + 2) - {n - 1}x" for n in range(2, 14))
                basis = None
        if not options:
            return []
        seed = "".join(context.target_skill_ids)
        index = sum(ord(ch) for ch in seed) % len(options)
        candidates: list[CandidateExercise] = []
        for offset in range(len(options)):
            statement = options[(index + offset) % len(options)]
            if not _candidate_allowed(statement, context):
                continue
            candidates.append(
                CandidateExercise(
                    student_id=context.student_id,
                    problem_statement=statement,
                    skill_ids=context.target_skill_ids,
                    concept_ids=context.target_concept_ids,
                    difficulty=context.desired_difficulty,
                    generated_by=(
                        "mt-template-document-grounded-v2"
                        if basis is not None
                        else self.generated_by
                    ),
                    context_version=context.context_version,
                    provenance=context.provenance,
                    material_basis=(basis,) if basis is not None else (),
                )
            )
            if len(candidates) >= max(1, count):
                break
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
    "若提供 excluded_problem_statements，不要重复这些题目；最终新题资格由宿主检查。"
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
    The legacy 0-1 mastery estimate is uncalibrated and is never sent; the
    model sees verified attempt outcomes instead.
    """
    public = {
        "target_skill_ids": list(context.target_skill_ids),
        "target_concept_ids": list(context.target_concept_ids),
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
            for entry in context.recent_attempt_summary[-20:]
        ],
        "desired_difficulty": context.desired_difficulty,
        "practice_purpose": context.practice_purpose,
        "excluded_problem_statements": list(context.excluded_problem_statements[:21]),
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
                "source_chunk_id": str(chunk.chunk_id),
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
    family = _family_for_targets(context)
    return selection is not None and family is not None and _document_basis(context, family) is not None


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
    if context.practice_purpose == "C":
        # Generic seed-bank difficulty does not encode a diagnosed subskill.
        # The bounded, verified foundation templates below do.
        return []
    wanted_skills = set(context.target_skill_ids) or None
    wanted_concepts = set(context.target_concept_ids) or None
    matches: list[CandidateExercise] = []
    for item in sorted(SEED_BANK, key=lambda item: abs(item.difficulty - context.desired_difficulty)):
        if wanted_skills and not (set(item.skill_ids) & wanted_skills):
            continue
        if wanted_concepts and not (set(item.concept_ids) & wanted_concepts):
            continue
        if item.difficulty != context.desired_difficulty or not _candidate_allowed(item.problem_statement, context):
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
        # A general seed-bank item does not necessarily exercise the verified
        # error. Use the constrained, independently released template first.
        if context.foundation_focus in {"equality_preservation", "signed_operations"}:
            focused = await self._template.generate(context, count=count)
            if focused:
                return focused[:count]
        bank = bank_candidates_for(context, count=count)
        if len(bank) >= count:
            return bank
        template_context = context.model_copy(update={"excluded_problem_statements": (*context.excluded_problem_statements, *(item.problem_statement for item in bank))})
        template_candidates = await self._template.generate(template_context, count=count - len(bank))
        if template_candidates:
            return (bank + template_candidates)[:count]
        return (bank + await self._try_llm(template_context, count=count - len(bank)))[:count]

    async def _generate_from_documents(
        self, context: PracticeGenerationContext, *, count: int
    ) -> list[CandidateExercise]:
        """Hits above threshold: consume document_context, do not drop recall.

        A checked method citation selects an actual template feature.
        Merely sending text to an LLM cannot establish material grounding.
        """
        template_candidates = await self._template.generate(context, count=count)
        if template_candidates:
            return template_candidates
        return await self._generate_without_documents(context, count=count)

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

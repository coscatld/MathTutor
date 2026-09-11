"""Explainable, discrete selection policy. No uncalibrated success probabilities."""
from __future__ import annotations

from typing import Sequence

from mathtutor.domain.practice_context import PracticeGenerationContext
from mathtutor.domain.practice_recommendation import PracticePurpose
from mathtutor.learning.skills import all_skill_ids

MAX_CANDIDATES = 3


def resolve_practice_purpose(
    requested: PracticePurpose, *, full_task_completed: bool,
    exposure_level: int, prerequisite_skill_ids: Sequence[str] = (),
    review_due: bool = False,
) -> PracticePurpose:
    """Teaching facts constrain the purpose; viewing/claiming understanding isn't success."""
    if requested in {"A1", "A2"}:
        if not full_task_completed:
            raise ValueError("整题尚未验证完成，不能签发完成型推荐")
        if exposure_level >= 5:
            return "B"
        return "A2" if exposure_level > 0 else "A1"
    if requested == "B" and exposure_level < 5:
        raise ValueError("完整答案尚未交付，不能签发看答案后检测")
    if requested == "C" and not prerequisite_skill_ids:
        raise ValueError("尚未定位具体先修缺口，不能自动降级为补基础")
    if requested == "E" and not review_due:
        raise ValueError("没有到期复习依据")
    return requested


def select_difficulty(
    context: PracticeGenerationContext, *, purpose: PracticePurpose,
    baseline: int = 2, requested: int | None = None,
) -> tuple[int, str]:
    if requested is not None:
        return max(1, min(5, requested)), "学生明确选择的离散难度"
    baseline = max(1, min(5, baseline))
    if purpose == "C":
        return max(1, baseline - 1), "已定位先修缺口，补基础使用较低离散难度"
    # Missing problem identity is legacy evidence, not proof of cross-item transfer.
    independent = {}
    for entry in context.recent_attempt_summary:
        if (entry.problem_id and entry.skill_id in context.target_skill_ids
                and entry.effective_assistance_level == 0):
            independent[entry.problem_id] = entry.correctness
    recent = list(independent.values())[-5:]
    if purpose in {"A1", "D", "E"} and len(recent) >= 3 and all(
        value == "correct" for value in recent[-3:]
    ):
        return min(5, baseline + 1), "至少三道不同题目的独立正确证据，提升一级"
    return baseline, "独立跨题证据不足或本次受助，保持当前离散难度"


def validate_targets(skill_ids: Sequence[str]) -> tuple[str, ...]:
    targets = tuple(dict.fromkeys(skill_ids))
    if not targets or not set(targets).issubset(all_skill_ids()):
        raise ValueError("目标知识点不在当前确定性验证覆盖范围")
    if len(targets) != 1:
        raise ValueError("请先选择一个具体练习知识点")
    return targets

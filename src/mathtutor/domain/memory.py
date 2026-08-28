"""Personal Memory KG domain — user-controlled, NON-authoritative knowledge.

The system has four strictly separate knowledge domains (design doc):

A. Curriculum Knowledge    — what math IS (concept/skill/prerequisite)
B. Student Model           — what the student CAN DO (authoritative:
                             mastery / assessment / evidence / misconception)
C. Personal Memory KG      — what the student PREFERS/GOALS (this module,
                             non-authoritative educational state)
D. User Document Knowledge — what the student IMPORTED (documents/chunks)

Personal Memory may store preferences, goals, interests, user notes and
AI inferences the user confirms. It is FORBIDDEN to store authoritative
educational facts here: mastery, assessment, misconception, verification
decisions. Deleting a memory NEVER changes mastery; the Student Model is
append-only evidence + derived projection and has no UI here.

Source types:
- ``USER_EXPLICIT`` — the student wrote it themselves;
- ``MODEL_INFERRED`` — the AI inferred it from interactions; MUST be
  clearly distinguishable from user content, confirmable or deletable;
- ``USER_CONFIRMED`` — the user confirmed a MODEL_INFERRED memory.

``retrieval_enabled`` is a data-layer switch: repositories enforce
owner + retrieval_enabled + deleted_at IS NULL — never frontend-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

MemoryType = Literal[
    "learning_preference",  # 学习偏好（节奏、方式）
    "expression_preference",  # 表达偏好（语言、称呼）
    "learning_goal",  # 学习目标
    "interest",  # 兴趣
    "user_note",  # 用户主动备注
    "example_preference",  # 偏好的例子类型
    "learning_scenario",  # 学习场景
    "ai_inference",  # AI 推测（需用户确认才可信）
]

MemorySourceType = Literal["USER_EXPLICIT", "MODEL_INFERRED", "USER_CONFIRMED"]

# These types belong to the AUTHORITATIVE domains (Student Model / verifier).
# Storing them as personal memory would create a second, weaker source of
# truth for the same fact — structurally forbidden at write time.
FORBIDDEN_MEMORY_TYPES: frozenset[str] = frozenset(
    {
        "mastery",
        "assessment",
        "misconception",
        "verification_decision",
        "attempt_correctness",
    }
)


def is_authoritative_domain(memory_type: str) -> bool:
    """True when the memory type belongs to an authoritative domain."""
    return memory_type in FORBIDDEN_MEMORY_TYPES


def assert_memory_writable(memory_type: str, source_type: str) -> None:
    """Fail closed on any attempt to smuggle authoritative facts into memory."""
    if memory_type in FORBIDDEN_MEMORY_TYPES:
        raise ValueError(
            f"memory_type {memory_type!r} is an authoritative educational fact "
            f"(mastery/assessment/misconception/verification) — it belongs to "
            f"the Student Model domain and cannot be stored as personal memory"
        )
    if source_type not in ("USER_EXPLICIT", "MODEL_INFERRED", "USER_CONFIRMED"):
        raise ValueError(f"unknown memory source_type: {source_type!r}")


class PersonalMemoryNode(BaseModel):
    """One user-controlled memory fact (subject → predicate → object)."""

    model_config = ConfigDict(frozen=True)

    memory_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    memory_type: MemoryType
    subject: str
    predicate: str
    object_json: dict
    source_type: MemorySourceType
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    retrieval_enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None

    def is_retrievable(self) -> bool:
        return self.retrieval_enabled and self.deleted_at is None


class PersonalMemoryEdge(BaseModel):
    """Optional relation between two memory nodes (owner-scoped).

    Edges are convenience structure for the KG — retrieval is node-based;
    an edge never grants cross-owner visibility and dies with soft delete.
    """

    model_config = ConfigDict(frozen=True)

    edge_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    source_node_id: UUID
    relation: str
    target_node_id: UUID
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None


def confirm_inference(node: PersonalMemoryNode) -> PersonalMemoryNode:
    """MODEL_INFERRED → USER_CONFIRMED (the only legal confirmation move)."""
    if node.source_type == "MODEL_INFERRED":
        return node.model_copy(
            update={
                "source_type": "USER_CONFIRMED",
                "updated_at": datetime.now(timezone.utc),
            }
        )
    if node.source_type == "USER_CONFIRMED":
        return node  # idempotent
    raise ValueError(
        f"only MODEL_INFERRED memories can be confirmed "
        f"(current source_type={node.source_type})"
    )


__all__ = [
    "FORBIDDEN_MEMORY_TYPES",
    "MemorySourceType",
    "MemoryType",
    "PersonalMemoryEdge",
    "PersonalMemoryNode",
    "assert_memory_writable",
    "confirm_inference",
    "is_authoritative_domain",
]

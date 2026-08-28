"""Curriculum graph: versions, nodes and edges.

Published curriculum versions are immutable; any change publishes a new
version (design doc §9.1). Exercise→concept/skill and
misconception→concept bindings use separate join tables, never the
node-to-node edge table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

NodeKind = Literal["chapter", "concept", "skill"]
EdgeKind = Literal["PREREQUISITE_OF", "PART_OF", "RELATED_TO"]
CurriculumStatus = Literal["draft", "published", "archived"]


class CurriculumVersion(BaseModel):
    """One immutable curriculum version."""

    model_config = ConfigDict(frozen=True)

    version_id: UUID = Field(default_factory=uuid4)
    code: str
    name: str
    status: CurriculumStatus = "draft"
    node_count: int = Field(ge=0, default=0)
    edge_count: int = Field(ge=0, default=0)
    released_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CurriculumNode(BaseModel):
    """Chapter / concept / skill node bound to exactly one curriculum version."""

    model_config = ConfigDict(frozen=True)

    node_id: UUID = Field(default_factory=uuid4)
    version_id: UUID
    code: str
    kind: NodeKind
    title: str
    stage: Literal["primary", "middle", "high"] | None = None
    grade: int | None = Field(default=None, ge=1, le=12)


class CurriculumEdge(BaseModel):
    """Directed edge inside one curriculum version (no cross-version edges)."""

    model_config = ConfigDict(frozen=True)

    edge_id: UUID = Field(default_factory=uuid4)
    version_id: UUID
    from_node_id: UUID
    to_node_id: UUID
    kind: EdgeKind


__all__ = ["CurriculumEdge", "CurriculumNode", "CurriculumVersion"]

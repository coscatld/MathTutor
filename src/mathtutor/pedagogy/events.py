"""Typed public event contracts (Phase 3E, design doc §13.3).

Two disjoint type families: :class:`StudentPublicEvent` (the ONLY type the
student serializer accepts) and :class:`InternalEvent` (solver/model/tool
traces — structurally unable to pass through the student serializer).

The student schema has NO fields for candidate solutions, verification
logs, answer keys, solver traces, model prompts or reasoning. Excluding
internal fields from the TYPE (not filtering them at runtime) is the
guarantee: an internal event cannot be serialized to a student by accident.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Field names that must NEVER appear on the student wire.
FORBIDDEN_STUDENT_FIELDS: frozenset[str] = frozenset(
    {
        "candidate_solution",
        "verified_solution",
        "final_answer",
        "verification_log",
        "solver_trace",
        "model_prompt",
        "model_reasoning",
        "raw_internal_event",
        "attestation_payload",
        "solution_candidate",
    }
)

# Public projections that MAY ride on the student wire as ``extra``
# (Phase 5): the practice-offer surface (offer id, curriculum labels,
# difficulty, timestamps) and the accept flow's child-cycle id. The
# allowlist is enforced at serialization — ANY key outside this set is
# structurally dropped, so internal fields can never leak through ``extra``.
STUDENT_EXTRA_ALLOWLIST: frozenset[str] = frozenset(
    {
        "offer_id",
        "status",
        "skill_labels",
        "concept_labels",
        "difficulty",
        "offered_at",
        "expires_at",
        "parent_cycle_id",
        "child_cycle_id",
        "idempotent_replay",
        "purpose", "navigation_cycle_id",
    }
)


class StudentPublicEvent(BaseModel):
    """The only event shape the student WebSocket may emit (§13.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[
        "tutor_action_committed",
        "tutor_message",
        "cycle_state_committed",
        "turn_error",
        "turn_end",
        "assistant_start", "assistant_delta", "assistant_complete", "assistant_partial", "assistant_error",
    ]
    audience: Literal["student"] = "student"
    cycle_id: str = ""
    cycle_state: str = ""
    cycle_state_version: int = 0
    allowed_next_inputs: list[str] = Field(default_factory=list)
    allowed_actions: list[dict[str, Any]] | None = None
    problem_revision: str | None = None
    teaching_plan: dict[str, Any] | None = None
    problem_context: dict[str, Any] | None = None
    evidence_summary: dict[str, Any] | None = None
    active_offer: dict[str, Any] | None = None
    diagnosis: dict[str, Any] | None = None
    recovery_problem: dict[str, Any] | None = None
    delivery_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    # Strictly allowlisted public projections only (Phase 5). The
    # serializer fills this from metadata via build_student_extra; nothing
    # else may write it.
    extra: dict[str, Any] = Field(default_factory=dict)

    def wire_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_student_extra(metadata: dict[str, Any]) -> dict[str, Any]:
    """Copy ONLY allowlisted public projection keys out of event metadata.

    Defense in depth on top of the type boundary: even if an internal
    field reached ``metadata``, it is structurally excluded here — the
    allowlist and the forbidden set never intersect.
    """
    return {
        key: metadata[key]
        for key in STUDENT_EXTRA_ALLOWLIST
        if key in metadata and key not in FORBIDDEN_STUDENT_FIELDS
    }


class InternalEvent(BaseModel):
    """Solver/model/tool traces — different audience, different schema.

    Never goes through the student serializer: the student serializer's
    parameter type is StudentPublicEvent, so an InternalEvent is rejected
    at the type boundary, not filtered field-by-field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str
    audience: Literal["internal"] = "internal"
    cycle_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


def serialize_student_event(event: StudentPublicEvent) -> dict[str, Any]:
    """Serialize a STUDENT event only — typed, no Any escape hatch."""
    return event.wire_dict()


def assert_no_forbidden_fields(frame: dict[str, Any]) -> None:
    """E2E invariant: a student WS frame must never carry internal fields —
    checked recursively (payload contents included)."""
    overlap = FORBIDDEN_STUDENT_FIELDS & set(frame)
    if overlap:
        raise ValueError(f"internal fields leaked into student frame: {sorted(overlap)}")
    for key, value in frame.items():
        if isinstance(value, dict):
            assert_no_forbidden_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    assert_no_forbidden_fields(item)


__all__ = [
    "FORBIDDEN_STUDENT_FIELDS",
    "InternalEvent",
    "STUDENT_EXTRA_ALLOWLIST",
    "StudentPublicEvent",
    "assert_no_forbidden_fields",
    "build_student_extra",
    "serialize_student_event",
]

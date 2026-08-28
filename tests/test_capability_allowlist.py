"""Capability allowlist + envelope smuggling rejection (Phase 0 §22/§23/§27)."""

from __future__ import annotations

import pytest

from mathtutor.security.allowlist import (
    MATHTUTOR_ALLOWED_CAPABILITIES,
    SecurityViolationError,
    validate_active_capability,
    validate_client_envelope,
)


class TestEnvelopeAllowlist:
    @pytest.mark.parametrize(
        "envelope",
        [
            {"command": "submit_problem", "payload": {"text": "2x=4"}},
            {
                "command": "submit_attempt",
                "payload": {"answer": "2"},
                "cycle_id": "c1",
                "session_id": "s1",
                "request_id": "r1",
                "expected_cycle_version": 3,
                "idempotency_key": "k1",
            },
        ],
    )
    def test_clean_envelopes_accepted(self, envelope: dict) -> None:
        assert validate_client_envelope(envelope) == envelope

    @pytest.mark.parametrize(
        "forbidden_key",
        [
            "student_id",
            "user_id",
            "owner_id",
            "roles",
            "role",
            "tenant_id",
            "capability",
            "active_capability",
            "tools",
            "enabled_tools",
            "allowed_builtin_tools",
            "system_prompt",
            "provider",
            "model",
            "filesystem_path",
            "plugin",
            "subagent",
            "mcp",
        ],
    )
    def test_forbidden_identity_and_tool_keys_rejected(self, forbidden_key: str) -> None:
        """A client can never smuggle identity, roles, capabilities or tools (§21)."""
        with pytest.raises(SecurityViolationError):
            validate_client_envelope({"command": "submit_problem", forbidden_key: "x"})

    def test_unknown_keys_rejected(self) -> None:
        with pytest.raises(SecurityViolationError):
            validate_client_envelope({"command": "submit_problem", "mystery_field": 1})

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(SecurityViolationError):
            validate_client_envelope(["submit_problem"])
        with pytest.raises(SecurityViolationError):
            validate_client_envelope("submit_problem")


class TestCapabilityAllowlist:
    @pytest.mark.parametrize(
        "capability", ["math_animator", "deep_research", "chat", "deep_solve", "visualize"]
    )
    def test_escalation_rejected(self, capability: str) -> None:
        """active_capability = anything but math_tutor → rejected (§22)."""
        with pytest.raises(SecurityViolationError):
            validate_active_capability(capability)

    def test_math_tutor_allowed(self) -> None:
        validate_active_capability("math_tutor")  # no raise

    def test_allowlist_is_exactly_math_tutor(self) -> None:
        assert MATHTUTOR_ALLOWED_CAPABILITIES == frozenset({"math_tutor"})

"""Execution-surface isolation: the student product has no tool/code/manim/
subagent/plugin surface (§7-§11, §22-§23)."""

from __future__ import annotations

import pytest

from mathtutor.capabilities.math_tutor import MathTutorCapability
from mathtutor.security.allowlist import (
    MATHTUTOR_FORBIDDEN_ROUTE_MARKERS,
    SecurityViolationError,
    validate_client_envelope,
)


class TestMathTutorCapabilitySurface:
    def test_manifest_registers_no_tools(self) -> None:
        capability = MathTutorCapability()
        assert capability.manifest.tools_used == []

    def test_manifest_stages_are_deterministic_pipeline(self) -> None:
        capability = MathTutorCapability()
        stages = capability.manifest.stages
        # The pipeline stages are fixed application stages — no tool-calling
        # stages like "planning with tools" or "agentic execution".
        assert "solve_and_verify" in stages
        assert "commit" in stages
        assert not any("tool" in s.lower() for s in stages)

    def test_student_cannot_inject_tools_via_envelope(self) -> None:
        for payload in (
            {"tools": ["code_execution"]},
            {"enabled_tools": ["shell"]},
            {"allowed_builtin_tools": ["web_search"]},
            {"plugin": "plugin_execute"},
            {"subagent": "research"},
            {"mcp": "server"},
        ):
            with pytest.raises(SecurityViolationError):
                validate_client_envelope(payload)

    def test_capability_allows_no_execution_capability_names(self) -> None:
        from mathtutor.security.allowlist import MATHTUTOR_ALLOWED_CAPABILITIES

        for forbidden in (
            "chat",
            "deep_solve",
            "deep_question",
            "deep_research",
            "math_animator",
            "visualize",
            "mastery_path",
        ):
            assert forbidden not in MATHTUTOR_ALLOWED_CAPABILITIES


class TestForbiddenRouteMarkersComplete:
    def test_markers_cover_all_execution_surfaces(self) -> None:
        """The route-inventory scan must catch every general execution surface."""
        for required in (
            "code-exec",
            "exec",
            "shell",
            "subagent",
            "plugin",
            "mcp",
            "manim",
            "animator",
            "visualize",
            "research",
            "obsidian",
            "partners",
            "chat",
            "web-search",
            "search",
            "rag",
        ):
            assert any(required in marker for marker in MATHTUTOR_FORBIDDEN_ROUTE_MARKERS)

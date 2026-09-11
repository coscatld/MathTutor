"""MathTutor product allowlists (design doc §13.1, §21-§23).

The student product is DEFAULT DENY + EXPLICIT ALLOW at every layer:

- capabilities: only ``math_tutor``;
- tools: none (the deterministic pipeline calls services directly);
- client envelope: only command/payload/cycle/session/version/idempotency keys;
- routes: the product app mounts only the allowlisted routers (see
  ``api/product_app.py``); ``MATHTUTOR_FORBIDDEN_ROUTE_MARKERS`` is used by
  CI/tests to prove no general DeepTutor execution surface is mounted.
"""

from __future__ import annotations

from typing import Any

# The only capability a student may route to (design doc §4.1, §13.1).
MATHTUTOR_ALLOWED_CAPABILITIES: frozenset[str] = frozenset({"math_tutor"})

# Keys a client envelope (§13.2) may carry. Everything else is rejected —
# this is what stops identity/tool/capability smuggling at the WS boundary.
MATHTUTOR_ENVELOPE_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "command",
        "protocol_version",
        "payload",
        "cycle_id",
        "session_id",
        "request_id",
        "expected_cycle_version",
        "expected_state_version",
        "problem_revision",
        "idempotency_key",
    }
)

# Identity/privilege/tool fields that must NEVER be client-controlled.
MATHTUTOR_ENVELOPE_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
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
    }
)

# Route-path markers that must never appear in the product app's route
# inventory (design doc §13.1 + §7). CI/tests scan ``app.routes`` for these.
MATHTUTOR_FORBIDDEN_ROUTE_MARKERS: tuple[str, ...] = (
    "code-exec",
    "code_execution",
    "exec",
    "shell",
    "terminal",
    "subagent",
    "plugin",
    "mcp",
    "manim",
    "animator",
    "visualize",
    "paper",
    "research",
    "co-writer",
    "co_writer",
    "obsidian",
    "partners",
    "book",
    "notebook",
    "question",
    "quiz",
    "voice",
    "skill",
    "space",
    "cron",
    "web_search",
    "web-search",
    "search",
    "rag",
    "chat",
    "chatbot",
    "deep_solve",
    "mastery",
    "agents",
)


class SecurityViolationError(Exception):
    """A client message violated the product security allowlists."""


def validate_client_envelope(raw: Any) -> dict[str, Any]:
    """Validate a client command envelope at the product boundary.

    Accepts a parsed JSON object; returns it unchanged when clean. Raises
    :class:`SecurityViolationError` on any forbidden/unknown top-level key —
    fail closed, never silently strip.
    """
    if not isinstance(raw, dict):
        raise SecurityViolationError("envelope must be a JSON object")
    if type(raw.get("protocol_version", 1)) is not int or raw.get("protocol_version", 1) not in (1, 2):
        raise SecurityViolationError("请更新客户端后重试。")
    for key in ("request_id", "idempotency_key"):
        if key in raw and (not isinstance(raw[key], str) or not raw[key].strip() or len(raw[key]) > 160):
            raise SecurityViolationError("请求标识无效，请重新打开对话。")
    for key in ("cycle_id", "problem_revision"):
        if key in raw and (not isinstance(raw[key], str) or len(raw[key]) > 128):
            raise SecurityViolationError("题目绑定无效，请重新同步对话。")
    for key in ("expected_cycle_version", "expected_state_version"):
        if key in raw and (type(raw[key]) is not int or raw[key] < 0):
            raise SecurityViolationError("状态版本无效，请重新同步对话。")
    if "expected_cycle_version" in raw and "expected_state_version" in raw and raw["expected_cycle_version"] != raw["expected_state_version"]:
        raise SecurityViolationError("状态版本不一致，请重新同步对话。")
    forbidden = [key for key in raw if key in MATHTUTOR_ENVELOPE_FORBIDDEN_KEYS]
    if forbidden:
        raise SecurityViolationError(
            f"forbidden envelope keys: {sorted(forbidden)} — identity, roles, "
            "capabilities and tools are server-owned"
        )
    unknown = [key for key in raw if key not in MATHTUTOR_ENVELOPE_ALLOWED_KEYS]
    if unknown:
        raise SecurityViolationError(f"unknown envelope keys: {sorted(unknown)}")
    return raw


def validate_active_capability(name: str | None) -> None:
    """Reject any capability the student product does not allow (default deny)."""
    if name is None:
        return
    if name not in MATHTUTOR_ALLOWED_CAPABILITIES:
        raise SecurityViolationError(
            f"capability {name!r} is not allowed in the MathTutor student product "
            f"(allowlist: {sorted(MATHTUTOR_ALLOWED_CAPABILITIES)})"
        )


__all__ = [
    "MATHTUTOR_ALLOWED_CAPABILITIES",
    "MATHTUTOR_ENVELOPE_ALLOWED_KEYS",
    "MATHTUTOR_ENVELOPE_FORBIDDEN_KEYS",
    "MATHTUTOR_FORBIDDEN_ROUTE_MARKERS",
    "SecurityViolationError",
    "validate_active_capability",
    "validate_client_envelope",
]

"""MathTutor TutorWriter configuration model (Phase 3C).

One place for the LLM-backed writer's runtime posture — no scattered
``if production`` branches. Loaded from the process environment with sane
development defaults; ``enabled=False`` keeps the deterministic
:class:`TemplateTutorWriter` as the only writer until a local model
endpoint is provisioned. Style follows ``security/settings.py`` (pydantic
model + explicit env loader, fully unit-testable without touching env).
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, field_validator

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})


class MathTutorWriterSettings(BaseModel):
    """Unified, testable configuration for the LLM-backed TutorWriter.

    When ``enabled`` is False, :meth:`LLMTutorWriter.write` falls back to the
    deterministic template writer WITHOUT touching the model layer
    (fail-closed default). An explicitly injected client still takes
    precedence: injection is an explicit opt-in by the wiring code.
    """

    # Gate for lazily provisioning the LLM client. Default False → template.
    enabled: bool = False
    # Model name reported in ``TutorWriterCandidate.model_name``; empty
    # means "provider default" (the writer then reports the client's model).
    model: str = ""
    # Per-turn budget for the model call, enforced with asyncio.wait_for.
    timeout_seconds: float = Field(default=120.0, gt=0)
    # Response token budget passed through to the provider.
    max_tokens: int = Field(default=1024, gt=0)

    @field_validator("model", mode="after")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        return value.strip()


def load_math_tutor_writer_settings() -> MathTutorWriterSettings:
    """Read the writer posture from the process environment.

    Environment variables:

    - ``MATHTUTOR_WRITER_ENABLED``: "true"/"1"/"yes"/"on" enables the LLM writer
    - ``MATHTUTOR_WRITER_MODEL``: model name (empty → provider default)
    - ``MATHTUTOR_WRITER_TIMEOUT``: per-turn timeout in seconds (default 120)
    - ``MATHTUTOR_WRITER_MAX_TOKENS``: response token budget (default 1024)

    Unparseable numeric values fall back to the defaults (fail-closed);
    a zero/negative value still fails loudly through pydantic validation.
    """
    enabled_raw = os.environ.get("MATHTUTOR_WRITER_ENABLED", "false").strip().lower()
    enabled = enabled_raw in _TRUE_VALUES

    timeout_seconds = 120.0
    try:
        timeout_seconds = float(os.environ.get("MATHTUTOR_WRITER_TIMEOUT", "120"))
    except ValueError:
        pass

    max_tokens = 1024
    try:
        max_tokens = int(os.environ.get("MATHTUTOR_WRITER_MAX_TOKENS", "1024"))
    except ValueError:
        pass

    return MathTutorWriterSettings(
        enabled=enabled,
        model=os.environ.get("MATHTUTOR_WRITER_MODEL", ""),
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
    )


__all__ = ["MathTutorWriterSettings", "load_math_tutor_writer_settings"]

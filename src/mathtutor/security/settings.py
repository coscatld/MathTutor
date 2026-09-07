"""MathTutor security configuration model (Phase 0, design doc §15/§18).

One place for the student product's security posture — no scattered
``if production`` branches. Loaded from process environment with sane
development defaults; ``create_math_tutor_app`` passes it to the startup
gate before any router is mounted.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Environment = Literal["development", "test", "production"]


class MathTutorSecuritySettings(BaseModel):
    """Unified, testable security configuration for the MathTutor product app."""

    environment: Environment = "development"
    # Packaged Electron is a production build but remains a single-user,
    # loopback-only local application.  This explicit mode is the only
    # production profile allowed to run without account authentication.
    local_desktop: bool = False
    # Network production requires auth. Development/test and the explicit
    # packaged-desktop profile may omit it only on loopback (startup gate).
    allow_loopback_without_auth: bool = True
    # The only capabilities the student product may route to.
    allowed_capabilities: frozenset[str] = frozenset({"math_tutor"})
    # DeepTutor general execution surfaces (code/subagent/plugin/manim/…).
    # The product app must stay False in production.
    execution_surfaces_enabled: bool = False
    # The TCP host the product app will bind (loopback gate input).
    host: str = "127.0.0.1"

    @field_validator("host", mode="after")
    @classmethod
    def _strip_host(cls, value: str) -> str:
        return value.strip().lower()

    def is_loopback(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1", ""}

    def in_production(self) -> bool:
        return self.environment == "production"


def load_math_tutor_security_settings() -> MathTutorSecuritySettings:
    """Read the security posture from the process environment.

    Environment variables:

    - ``MATHTUTOR_ENVIRONMENT``: development | test | production
      (``DEEPTUTOR_ENVIRONMENT`` is a deprecated one-release upgrade alias)
    - ``MATHTUTOR_DESKTOP``: explicit packaged local-desktop profile
    - ``MATHTUTOR_ALLOW_LOOPBACK_WITHOUT_AUTH``: "true"/"false"
    - ``MATHTUTOR_EXECUTION_SURFACES``: "true"/"false"
    - ``MATHTUTOR_HOST``: bind host for the loopback gate
    """
    environment = (
        os.environ.get("MATHTUTOR_ENVIRONMENT")
        or os.environ.get("DEEPTUTOR_ENVIRONMENT")
        or "development"
    ).strip().lower()
    if environment not in {"development", "test", "production"}:
        environment = "development"
    return MathTutorSecuritySettings(
        environment=environment,  # type: ignore[arg-type]
        local_desktop=os.environ.get("MATHTUTOR_DESKTOP", "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        allow_loopback_without_auth=os.environ.get(
            "MATHTUTOR_ALLOW_LOOPBACK_WITHOUT_AUTH", "true"
        ).strip().lower() != "false",
        execution_surfaces_enabled=os.environ.get(
            "MATHTUTOR_EXECUTION_SURFACES", "false"
        ).strip().lower() == "true",
        host=os.environ.get("MATHTUTOR_HOST", "127.0.0.1"),
    )


__all__ = ["MathTutorSecuritySettings", "load_math_tutor_security_settings"]

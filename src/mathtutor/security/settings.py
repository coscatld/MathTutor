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


def _transport_values(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.environ.get(name, default).split(",") if value.strip())


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
    # Exact authorities/origins, including the real port. Never trust forwarded
    # headers or accept arbitrary loopback ports. Desktop overrides these on
    # each launch; dev/native clients configure them explicitly.
    allowed_hosts: tuple[str, ...] = Field(default_factory=lambda: _transport_values(
        "MATHTUTOR_ALLOWED_HOSTS", "127.0.0.1:8001,localhost:8001"), validate_default=True)
    allowed_origins: tuple[str, ...] = Field(default_factory=lambda: _transport_values(
        "MATHTUTOR_ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000"), validate_default=True)
    bridge_secret: str = Field(default_factory=lambda: os.environ.get("MATHTUTOR_BRIDGE_SECRET", ""), repr=False, exclude=True)

    @field_validator("allowed_origins")
    @classmethod
    def _exact_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        from urllib.parse import urlsplit
        for value in values:
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment or value != f"{parsed.scheme}://{parsed.netloc}"):
                raise ValueError("allowed_origins must contain exact HTTP(S) origins")
            _ = parsed.port  # reject malformed authorities
        return values

    @field_validator("allowed_hosts")
    @classmethod
    def _exact_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        from urllib.parse import urlsplit
        for value in values:
            parsed = urlsplit("http://" + value)
            if (not parsed.hostname or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment or "*" in value
                    or value != parsed.netloc or value != value.lower()):
                raise ValueError("allowed_hosts must contain exact authorities")
            _ = parsed.port
        if not values:
            raise ValueError("allowed_hosts must not be empty")
        return values

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

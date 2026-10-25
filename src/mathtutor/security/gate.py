"""MathTutor startup security gate (design doc §15, P0).

Every P0 violation raises :class:`SecurityConfigurationError` — the product
app REFUSES TO START. No warnings-and-continue path exists.
"""

from __future__ import annotations

import logging

from mathtutor.security.settings import MathTutorSecuritySettings

logger = logging.getLogger(__name__)

# Secrets that are never acceptable for production auth.
_WEAK_SECRETS = frozenset(
    {
        "",
        "default",
        "development",
        "changeme",
        "change-me",
        "secret",
        "password",
        "admin",
        "test",
        "testing",
        "letmein",
        "123456",
    }
)

_MIN_SECRET_LENGTH = 16


class SecurityConfigurationError(Exception):
    """A P0 security constraint is violated; startup must abort."""


def _is_weak_secret(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _WEAK_SECRETS or (
        len(value.strip()) < _MIN_SECRET_LENGTH and value.strip() != ""
    )


def validate_math_tutor_security(
    settings: MathTutorSecuritySettings,
    *,
    auth_enabled: bool,
    auth_secret: str = "",
    password_hash: str = "",
) -> None:
    """Validate the full P0 security posture before the product app exists.

    Rules (design doc §15, §26):

    - network production requires auth (fail closed);
    - packaged local desktop may omit auth only on loopback;
    - weak/default secrets refuse startup whenever auth is enabled;
    - auth-disabled is allowed only in development/test or the explicit
      packaged-desktop profile, and always on loopback;
    - execution surfaces must be disabled in production;
    - the capability allowlist must contain ``math_tutor``.
    """
    if "math_tutor" not in settings.allowed_capabilities:
        raise SecurityConfigurationError(
            "allowed_capabilities must include 'math_tutor' — the student "
            "product has no routable capability"
        )

    if settings.local_desktop and len(settings.bridge_secret) < 32:
        raise SecurityConfigurationError(
            "local desktop requires a per-launch bridge credential of at least 32 characters"
        )

    if settings.in_production():
        local_desktop_without_auth = (
            settings.local_desktop
            and settings.allow_loopback_without_auth
            and settings.is_loopback()
        )
        if not auth_enabled and not local_desktop_without_auth:
            raise SecurityConfigurationError(
                "network production requires auth: auth.enabled=false is only "
                "allowed for the loopback-only packaged desktop"
            )
        if settings.execution_surfaces_enabled:
            raise SecurityConfigurationError(
                "production refuses to start with execution surfaces enabled "
                "(code/subagent/plugin/manim surfaces are excluded from the "
                "student product)"
            )
    else:
        if not auth_enabled and settings.allow_loopback_without_auth and not settings.is_loopback():
            raise SecurityConfigurationError(
                f"auth is disabled but bind host {settings.host!r} is not "
                "loopback — refuse to start (development without auth is "
                "loopback-only)"
            )
        if not auth_enabled and not settings.allow_loopback_without_auth:
            raise SecurityConfigurationError(
                "auth is disabled and loopback-without-auth is forbidden by "
                "configuration — refuse to start"
            )

    if auth_enabled:
        if _is_weak_secret(auth_secret):
            raise SecurityConfigurationError(
                "auth is enabled but the token secret is missing or weak — "
                "refuse to start"
            )
        if password_hash.strip() and _is_weak_secret(password_hash):
            raise SecurityConfigurationError(
                "auth is enabled but the bootstrap password hash is weak — "
                "refuse to start"
            )


__all__ = ["SecurityConfigurationError", "validate_math_tutor_security"]

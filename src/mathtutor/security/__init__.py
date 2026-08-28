"""MathTutor Phase 0 security: config model, owner scopes, startup gate, allowlists."""

from __future__ import annotations

from mathtutor.security.allowlist import (
    MATHTUTOR_ALLOWED_CAPABILITIES,
    MATHTUTOR_ENVELOPE_ALLOWED_KEYS,
    MATHTUTOR_ENVELOPE_FORBIDDEN_KEYS,
    MATHTUTOR_FORBIDDEN_ROUTE_MARKERS,
    validate_client_envelope,
)
from mathtutor.security.gate import (
    SecurityConfigurationError,
    validate_math_tutor_security,
)
from mathtutor.security.scopes import (
    IdentityResolutionError,
    PrincipalScope,
    StudentOwnerScope,
    dev_student_owner,
    resolve_student_owner,
    resolve_student_owner_scope,
)
from mathtutor.security.settings import (
    MathTutorSecuritySettings,
    load_math_tutor_security_settings,
)

__all__ = [
    "IdentityResolutionError",
    "MATHTUTOR_ALLOWED_CAPABILITIES",
    "MATHTUTOR_ENVELOPE_ALLOWED_KEYS",
    "MATHTUTOR_ENVELOPE_FORBIDDEN_KEYS",
    "MATHTUTOR_FORBIDDEN_ROUTE_MARKERS",
    "MathTutorSecuritySettings",
    "PrincipalScope",
    "SecurityConfigurationError",
    "StudentOwnerScope",
    "dev_student_owner",
    "load_math_tutor_security_settings",
    "resolve_student_owner",
    "resolve_student_owner_scope",
    "validate_client_envelope",
    "validate_math_tutor_security",
]

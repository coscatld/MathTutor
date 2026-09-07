"""Owner scopes for the MathTutor student product (design doc §11.1).

``PrincipalScope`` / ``StudentOwnerScope`` can ONLY be created by the auth
layer (HTTP/WS dependency) or by the trusted local fallback — never deserialized
from a request body, query parameter, WS payload, LLM or tool.

The capability and repositories accept a pre-built scope; the client can at
most send session/cycle/version/command (see ``allowlist.py``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from mathtutor.security.settings import MathTutorSecuritySettings

# Fixed, server-owned, loopback-only fallback identity. These values are used
# when a local install has no historical single-account owner to preserve.
LOCAL_ADMIN_ID = "local-admin"
LOCAL_ADMIN_USERNAME = "local"

DEV_STUDENT_ID = LOCAL_ADMIN_ID


class IdentityResolutionError(Exception):
    """Raised when a MathTutor turn has no trustworthy authenticated identity."""


@dataclass(frozen=True, slots=True)
class PrincipalScope:
    """Authenticated principal, created exclusively by the auth layer."""

    user_id: str
    username: str
    role: str
    tenant_id: str | None = None


@dataclass(frozen=True, slots=True)
class StudentOwnerScope:
    """Owner scope bound to one student's private data.

    Phase 0 maps ``student_id`` to the authenticated user id (the student
    profile table arrives in Phase 1); the structure is frozen now so the
    mapping can change later without touching the capability layer.
    """

    principal: PrincipalScope
    student_id: str


def student_uuid(student_id: str) -> UUID:
    """Deterministic UUID for a student id of arbitrary shape.

    DeepTutor user ids are either UUID hex or legacy strings like
    ``local-admin``; tutoring aggregates need a UUID key. The hash keeps the
    mapping stable and collision-safe without leaking the raw id shape.
    """
    try:
        return UUID(student_id)
    except ValueError:
        digest = hashlib.sha256(student_id.encode("utf-8")).hexdigest()[:32]
        return UUID(hex=digest)


def dev_student_owner(settings: MathTutorSecuritySettings | None = None) -> StudentOwnerScope:
    """Server-side fallback identity for an auth-disabled loopback runtime.

    Allowed ONLY by the startup gate (development/test or explicit packaged
    desktop + loopback). It is a fixed server-generated identity — the client
    can never choose it — and matches the historical local-admin identity.
    """
    principal = PrincipalScope(
        user_id=DEV_STUDENT_ID, username=LOCAL_ADMIN_USERNAME, role="admin"
    )
    return StudentOwnerScope(principal=principal, student_id=DEV_STUDENT_ID)


def resolve_student_owner_scope() -> StudentOwnerScope:
    """Reject calls that bypass the standalone auth-owned scope boundary.

    The standalone product has no process-global current-user context. HTTP and
    WS auth construct :class:`StudentOwnerScope` explicitly and attach it to the
    server-owned request context. Optional host adapters must do the same.
    """
    raise IdentityResolutionError("no authenticated principal — turn rejected")


def resolve_student_owner(
    context: Any,
    *,
    settings: MathTutorSecuritySettings | None = None,
) -> StudentOwnerScope:
    """Resolve the owner for one turn.

    Priority:

    1. a pre-built :class:`StudentOwnerScope` placed in
       ``context.metadata["student_owner"]`` by the auth layer (product WS);
    2. the fixed local identity — only in a permitted loopback profile.

    A plain dict in metadata is NEVER accepted (identity objects must be
    constructed server-side); anything else fails closed.
    """
    metadata = getattr(context, "metadata", None) or {}
    owner = metadata.get("student_owner")
    if isinstance(owner, StudentOwnerScope):
        return owner
    if owner is not None:
        raise IdentityResolutionError("untrusted identity object in context metadata")

    try:
        return resolve_student_owner_scope()
    except IdentityResolutionError:
        pass

    if settings is None:
        from mathtutor.security.settings import load_math_tutor_security_settings

        settings = load_math_tutor_security_settings()
    if (
        (settings.environment in {"development", "test"} or settings.local_desktop)
        and settings.allow_loopback_without_auth
        and settings.is_loopback()
    ):
        return dev_student_owner(settings)

    raise IdentityResolutionError("no authenticated principal — turn rejected")


__all__ = [
    "DEV_STUDENT_ID",
    "IdentityResolutionError",
    "PrincipalScope",
    "StudentOwnerScope",
    "dev_student_owner",
    "resolve_student_owner",
    "resolve_student_owner_scope",
    "student_uuid",
]

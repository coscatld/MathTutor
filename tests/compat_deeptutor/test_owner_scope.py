"""Owner scope resolution: identity is server-owned, never client-supplied (§3, §27)."""

from __future__ import annotations

import pytest

from mathtutor.security.scopes import (
    DEV_STUDENT_ID,
    IdentityResolutionError,
    PrincipalScope,
    StudentOwnerScope,
    dev_student_owner,
    resolve_student_owner,
    resolve_student_owner_scope,
    student_uuid,
)
from mathtutor.security.settings import MathTutorSecuritySettings


class _FakeContext:
    def __init__(self, metadata: dict | None = None) -> None:
        self.metadata = metadata or {}


class TestScopeConstruction:
    def test_scopes_are_frozen(self) -> None:
        principal = PrincipalScope(user_id="u1", username="alice", role="user")
        owner = StudentOwnerScope(principal=principal, student_id="u1")
        with pytest.raises(Exception):
            principal.role = "admin"  # type: ignore[misc]
        with pytest.raises(Exception):
            owner.student_id = "u2"  # type: ignore[misc]

    def test_student_uuid_stable_mapping(self) -> None:
        a = student_uuid("local-admin")
        b = student_uuid("local-admin")
        assert a == b  # deterministic
        assert a != student_uuid("other-user")

    def test_student_uuid_accepts_real_uuids(self) -> None:
        from uuid import UUID

        value = "550e8400-e29b-41d4-a716-446655440000"
        assert student_uuid(value) == UUID(value)


class TestResolutionFromContextMetadata:
    def test_prebuilt_scope_accepted(self) -> None:
        owner = StudentOwnerScope(
            principal=PrincipalScope(user_id="u1", username="a", role="user"),
            student_id="u1",
        )
        context = _FakeContext(metadata={"student_owner": owner})
        assert resolve_student_owner(context) is owner

    def test_plain_dict_rejected(self) -> None:
        """A dict in metadata is NOT an identity — fail closed (§3)."""
        context = _FakeContext(
            metadata={"student_owner": {"student_id": "forged", "user_id": "admin"}}
        )
        with pytest.raises(IdentityResolutionError):
            resolve_student_owner(context, settings=_prod_settings())

    def test_missing_identity_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import deeptutor.multi_user.context as user_context

        monkeypatch.setattr(user_context, "_current_user", _empty_contextvar())
        context = _FakeContext()
        with pytest.raises(IdentityResolutionError):
            resolve_student_owner(context, settings=_prod_settings())

    def test_dev_fallback_only_in_loopback_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import deeptutor.multi_user.context as user_context

        monkeypatch.setattr(user_context, "_current_user", _empty_contextvar())
        context = _FakeContext()
        dev_settings = MathTutorSecuritySettings(
            environment="development", host="127.0.0.1"
        )
        owner = resolve_student_owner(context, settings=dev_settings)
        assert owner.student_id == DEV_STUDENT_ID
        # Dev identity mirrors DeepTutor's local-admin identity for the
        # auth-disabled local mode.
        assert owner.principal.role == "admin"


class TestResolutionFromCurrentUser:
    def test_authenticated_user_becomes_owner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from deeptutor.multi_user.context import (
            get_current_user_or_none,
            set_current_user,
            user_from_token_payload,
        )

        class _Payload:
            user_id = "user-123"
            username = "alice"
            role = "user"

        token = set_current_user(user_from_token_payload(_Payload()))
        try:
            owner = resolve_student_owner_scope()
            assert owner.student_id == "user-123"
            assert owner.principal.role == "user"
        finally:
            from deeptutor.multi_user.context import reset_current_user

            reset_current_user(token)
        assert get_current_user_or_none() is None

    def test_no_user_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No authenticated principal → IdentityResolutionError, never a
        synthetic anonymous identity (§15)."""
        import deeptutor.multi_user.context as user_context

        monkeypatch.setattr(user_context, "_current_user", _empty_contextvar())
        with pytest.raises(IdentityResolutionError):
            resolve_student_owner_scope()

    def test_dev_student_owner_is_server_generated(self) -> None:
        owner = dev_student_owner()
        assert owner.student_id == DEV_STUDENT_ID
        assert owner.principal.user_id == DEV_STUDENT_ID


def _prod_settings() -> MathTutorSecuritySettings:
    return MathTutorSecuritySettings(environment="production")


def _empty_contextvar():
    from contextvars import ContextVar

    return ContextVar("deeptutor_current_user_test", default=None)

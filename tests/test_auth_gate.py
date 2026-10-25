"""Startup security gate: production auth, weak secrets, loopback (Phase 0 §26)."""

from __future__ import annotations

import pytest

from mathtutor.security.gate import (
    SecurityConfigurationError,
    validate_math_tutor_security,
)
from mathtutor.security.settings import MathTutorSecuritySettings


def _settings(**kwargs) -> MathTutorSecuritySettings:
    return MathTutorSecuritySettings(**kwargs)


class TestProductionAuthGate:
    def test_case_a_production_auth_disabled_fails(self) -> None:
        """production + auth=false → startup failed (§26 Case A)."""
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(environment="production"), auth_enabled=False
            )

    def test_case_b_production_weak_secret_fails(self) -> None:
        """production + auth=true + weak secret → startup failed (§26 Case B)."""
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(environment="production"),
                auth_enabled=True,
                auth_secret="changeme",
            )

    def test_case_b2_weak_password_hash_fails(self) -> None:
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(environment="production"),
                auth_enabled=True,
                auth_secret="x" * 64,
                password_hash="password",
            )

    def test_production_execution_surfaces_forbidden(self) -> None:
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(environment="production", execution_surfaces_enabled=True),
                auth_enabled=True,
                auth_secret="x" * 64,
            )

    def test_production_valid_config_passes(self) -> None:
        validate_math_tutor_security(
            _settings(environment="production"),
            auth_enabled=True,
            auth_secret="x" * 64,
        )

    def test_packaged_local_desktop_auth_disabled_loopback_passes(self) -> None:
        validate_math_tutor_security(
            _settings(
                environment="production",
                local_desktop=True,
                host="127.0.0.1",
            ),
            auth_enabled=False,
        )

    def test_local_desktop_requires_per_launch_bridge_credential(self) -> None:
        with pytest.raises(SecurityConfigurationError, match="bridge credential"):
            validate_math_tutor_security(
                _settings(environment="production", local_desktop=True, bridge_secret=""),
                auth_enabled=False,
            )

    def test_packaged_local_desktop_auth_disabled_non_loopback_fails(self) -> None:
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(
                    environment="production",
                    local_desktop=True,
                    host="0.0.0.0",
                ),
                auth_enabled=False,
            )

    def test_short_secret_rejected_when_auth_enabled(self) -> None:
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(environment="development"),
                auth_enabled=True,
                auth_secret="short",
            )


class TestLoopbackGate:
    def test_case_c_dev_auth_disabled_loopback_allowed(self) -> None:
        """development + auth=false + 127.0.0.1 → allowed (§26 Case C)."""
        validate_math_tutor_security(
            _settings(environment="development", host="127.0.0.1"),
            auth_enabled=False,
        )

    def test_case_d_dev_auth_disabled_non_loopback_fails(self) -> None:
        """development + auth=false + 0.0.0.0 → refused (§26 Case D)."""
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(environment="development", host="0.0.0.0"),
                auth_enabled=False,
            )

    def test_dev_auth_disabled_loopback_forbidden_by_setting_fails(self) -> None:
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(
                    environment="development",
                    host="127.0.0.1",
                    allow_loopback_without_auth=False,
                ),
                auth_enabled=False,
            )


class TestCapabilityAllowlistSanity:
    def test_allowlist_must_contain_math_tutor(self) -> None:
        with pytest.raises(SecurityConfigurationError):
            validate_math_tutor_security(
                _settings(allowed_capabilities=frozenset({"chat"})),
                auth_enabled=False,
            )

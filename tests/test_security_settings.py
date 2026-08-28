"""MathTutorSecuritySettings: model invariants and env loading (Phase 0 §18)."""

from __future__ import annotations

import pytest

from mathtutor.security.settings import (
    MathTutorSecuritySettings,
    load_math_tutor_security_settings,
)


class TestModelInvariants:
    def test_defaults_are_development_loopback(self) -> None:
        settings = MathTutorSecuritySettings()
        assert settings.environment == "development"
        assert settings.allow_loopback_without_auth is True
        assert settings.execution_surfaces_enabled is False
        assert settings.allowed_capabilities == frozenset({"math_tutor"})
        assert settings.is_loopback()

    def test_loopback_hosts(self) -> None:
        for host in ("127.0.0.1", "localhost", "::1", ""):
            assert MathTutorSecuritySettings(host=host).is_loopback()

    def test_non_loopback_hosts(self) -> None:
        for host in ("0.0.0.0", "192.168.1.5", "example.com"):
            assert not MathTutorSecuritySettings(host=host).is_loopback()

    def test_host_normalized(self) -> None:
        assert MathTutorSecuritySettings(host=" 127.0.0.1 ").host == "127.0.0.1"

    def test_production_flag(self) -> None:
        assert MathTutorSecuritySettings(environment="production").in_production()
        assert not MathTutorSecuritySettings(environment="development").in_production()


class TestEnvLoading:
    def test_env_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MATHTUTOR_ENVIRONMENT", "production")
        monkeypatch.setenv("MATHTUTOR_ALLOW_LOOPBACK_WITHOUT_AUTH", "false")
        monkeypatch.setenv("MATHTUTOR_EXECUTION_SURFACES", "true")
        monkeypatch.setenv("MATHTUTOR_HOST", "0.0.0.0")
        settings = load_math_tutor_security_settings()
        assert settings.environment == "production"
        assert settings.allow_loopback_without_auth is False
        assert settings.execution_surfaces_enabled is True
        assert settings.host == "0.0.0.0"

    def test_invalid_environment_falls_back_to_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MATHTUTOR_ENVIRONMENT", "staging")
        assert load_math_tutor_security_settings().environment == "development"

    def test_defaults_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in (
            "MATHTUTOR_ENVIRONMENT",
            "MATHTUTOR_ALLOW_LOOPBACK_WITHOUT_AUTH",
            "MATHTUTOR_EXECUTION_SURFACES",
            "MATHTUTOR_HOST",
        ):
            monkeypatch.delenv(key, raising=False)
        settings = load_math_tutor_security_settings()
        assert settings.environment == "development"
        assert settings.is_loopback()

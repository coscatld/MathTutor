"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True)
def _explicit_native_test_transport(monkeypatch):
    """Business tests are explicit native clients, never a product bypass.

    Boundary regressions override/clear this header to exercise rejection.
    Real runtimes retain secure defaults and receive no test-host exception.
    """
    from starlette.testclient import TestClient

    monkeypatch.setenv("MATHTUTOR_BRIDGE_SECRET", "isolated-native-test-credential-" + "x" * 32)
    monkeypatch.setenv("MATHTUTOR_ALLOWED_HOSTS", "testserver,127.0.0.1:8001,localhost:8001")
    original = TestClient.__init__

    def explicit_client(self, app, *args, **kwargs):
        settings = getattr(getattr(app, "state", None), "math_tutor_security", None)
        if settings is not None:
            headers = dict(kwargs.get("headers") or {})
            if not any(name.lower() == "x-mathtutor-bridge" for name in headers):
                headers["X-MathTutor-Bridge"] = settings.bridge_secret
            kwargs["headers"] = headers
        original(self, app, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", explicit_client)


@pytest.fixture(autouse=True)
def _isolated_encryption_keys():
    """Never touch the developer's real keychain: each test gets fresh keys."""
    from mathtutor.infrastructure import db_crypto
    from mathtutor.infrastructure.secret_store import InMemorySecretStore
    db_crypto.use_keystore(InMemorySecretStore())
    yield
    db_crypto.use_keystore(InMemorySecretStore())

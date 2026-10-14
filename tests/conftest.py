"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_encryption_keys():
    """Never touch the developer's real keychain: each test gets fresh keys."""
    from mathtutor.infrastructure import db_crypto
    from mathtutor.infrastructure.secret_store import InMemorySecretStore
    db_crypto.use_keystore(InMemorySecretStore())
    yield
    db_crypto.use_keystore(InMemorySecretStore())

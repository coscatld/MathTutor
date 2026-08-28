"""Pure cross-platform release contracts; these are not target-machine tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mathtutor.api import desktop_api
from mathtutor.infrastructure import keychain_secret_store as keychain


@pytest.mark.asyncio
async def test_linux_secret_tool_absent_is_degraded_and_never_plaintext(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Simulated Linux contract only: absence fails closed and creates no file.

    This runs on macOS with injected platform/probe results. It must never be
    reported as a Linux target-machine PASS.
    """

    monkeypatch.setattr(keychain.platform, "system", lambda: "Linux")
    monkeypatch.setattr(keychain, "_which", lambda _command: False)
    monkeypatch.chdir(tmp_path)
    store = keychain.KeychainSecretStore(service="com.mathtutor.product.test")
    secret = "must-not-reach-a-plaintext-file"

    assert store.available() is False
    before = tuple(tmp_path.iterdir())
    for operation in (
        lambda: store.put("key", secret),
        lambda: store.get("key"),
        lambda: store.delete("key"),
    ):
        with pytest.raises(keychain.KeychainUnavailableError) as error:
            await operation()
        assert secret not in str(error.value)

    status, detail = await desktop_api._secret_store_check(
        SimpleNamespace(secret_store=store)
    )
    assert status == "degraded"
    assert "secret-tool" in detail
    assert tuple(tmp_path.iterdir()) == before

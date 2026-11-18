import asyncio
import traceback

import httpx
import pytest

from mathtutor.infrastructure import zhihu
from mathtutor.infrastructure.zhihu import ZhihuClient, ZhihuError


def client_with(store):
    def refuse_network(request):
        pytest.fail("Credential failures must not send an HTTP request")
    return ZhihuClient(store, transport=httpx.MockTransport(refuse_network))


async def invoke(client, operation):
    if operation == "configuration":
        return await client.configuration("local-admin")
    return await client.search("local-admin", "分数学习")


@pytest.mark.parametrize("operation", ["configuration", "search"])
async def test_secret_store_error_becomes_safe_typed_failure(operation):
    class Store:
        async def get(self, key):
            raise OSError("sensitive-keychain-details-and-private-path")
    with pytest.raises(ZhihuError) as raised:
        await invoke(client_with(Store()), operation)
    assert raised.value.kind == "credential_unavailable"
    assert "sensitive-keychain" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("operation", ["configuration", "search"])
async def test_secret_read_timeout_cancels_store_and_remains_distinct(operation, monkeypatch):
    monkeypatch.setattr(zhihu, "SECRET_READ_TIMEOUT", 0.01)
    cancelled = asyncio.Event()
    class Store:
        async def get(self, key):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    with pytest.raises(ZhihuError) as raised:
        await invoke(client_with(Store()), operation)
    assert raised.value.kind == "credential_timeout" and cancelled.is_set()


@pytest.mark.parametrize("operation", ["configuration", "search"])
async def test_caller_cancellation_is_not_converted_to_credential_failure(operation):
    entered, cancelled = asyncio.Event(), asyncio.Event()
    class Store:
        async def get(self, key):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    task = asyncio.create_task(invoke(client_with(Store()), operation))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

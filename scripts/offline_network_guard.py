"""Opt-in pytest plugin: real external HTTP dispatch is forbidden.

Mock/ASGI transports remain usable for production Gateway contract tests.
"""
import httpx


def pytest_configure(config):
    original_async = httpx.AsyncClient._send_single_request
    original_sync = httpx.Client._send_single_request
    def allowed(client, request):
        transport = client._transport_for_url(request.url)
        return (isinstance(transport, (httpx.MockTransport, httpx.ASGITransport))
                or type(transport).__module__.startswith("starlette.testclient")
                or request.url.host in {"127.0.0.1", "localhost", "::1"})
    async def guarded_async(client, request):
        if not allowed(client, request):
            raise AssertionError("Offline test guard blocked external HTTP dispatch")
        return await original_async(client, request)
    def guarded_sync(client, request):
        if not allowed(client, request):
            raise AssertionError("Offline test guard blocked external HTTP dispatch")
        return original_sync(client, request)
    httpx.AsyncClient._send_single_request = guarded_async
    httpx.Client._send_single_request = guarded_sync
    config._offline_original_http = (original_async, original_sync)


def pytest_unconfigure(config):
    originals = getattr(config,"_offline_original_http",None)
    if originals:
        httpx.AsyncClient._send_single_request, httpx.Client._send_single_request = originals

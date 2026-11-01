"""Configuration ownership and atomic commit regression tests; all HTTP is mocked."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from mathtutor.api import desktop_api
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.infrastructure import gateway_config
from mathtutor.infrastructure.gateway_config import GatewayConfigService, GatewayRevisionConflict
from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole
from mathtutor.infrastructure.secret_store import InMemorySecretStore

pytestmark = pytest.mark.asyncio
SECRET = "fake-original-credential"

async def configured(tmp_path, *, model="model-a"):
    store = InMemorySecretStore()
    gateway = GenerativeModelGateway(store)
    path = tmp_path / "gateway.json"
    service = GatewayConfigService(gateway, store, path)
    await service.apply_config(preset_id="custom", api_key=SECRET, base_url="https://a.invalid/v1", model=model)
    return service, gateway, store, path


def transport(gateway, handler):
    for role in (ModelRole.TUTOR_WRITER, ModelRole.PRACTICE_GENERATOR):
        gateway.provider_for(role)._transport = httpx.MockTransport(handler)


def chat(status=200, text="ok"):
    return httpx.Response(status, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


@pytest.mark.parametrize("stage", ["discovery", "chat"])
@pytest.mark.parametrize("replacement", ["provider", "model", "delete"])
@pytest.mark.parametrize("outcome", ["success", "failure"])
async def test_delayed_probe_never_publishes_to_a_new_configuration(tmp_path, stage, replacement, outcome):
    service, gateway, store, path = await configured(tmp_path, model="" if stage == "discovery" else "model-a")
    original = service.current_config()
    entered = asyncio.Event()
    release = asyncio.get_running_loop().create_future()
    calls = []

    async def handler(request):
        calls.append((str(request.url), request.headers.get("authorization"), json.loads(request.content) if request.content else None))
        if (stage == "discovery" and request.url.path.endswith("/models")) or stage == "chat":
            entered.set()
            await release
        if outcome == "failure":
            return httpx.Response(401, text=f"unauthorized {SECRET}")
        return httpx.Response(200, json={"data": [{"id": "discovered-a"}]}) if request.url.path.endswith("/models") else chat()

    transport(gateway, handler)
    probe = asyncio.create_task(service.test_connection(expected_revision=original["revision"], expected_epoch=original["epoch"], operation_id="probe-a"))
    await asyncio.wait_for(entered.wait(), 2)
    if replacement == "delete":
        await service.remove_api_key()
    else:
        await service.apply_config(preset_id="openai" if replacement == "provider" else "custom", api_key="fake-new-credential", base_url="https://b.invalid/v1", model="model-b")
    current = service.current_config()
    old_file = path.read_bytes()
    release.set_result(None)
    result = await probe
    assert not result.accepted
    assert result.revision == original["revision"] and result.current_revision == current["revision"]
    assert result.operation_id == "probe-a" and result.provider_id == "custom"
    assert SECRET not in result.model_dump_json()
    assert service.current_config() == current and path.read_bytes() == old_file
    assert service.connection_status() == ("unconfigured" if replacement == "delete" else "configured")
    assert all("a.invalid" in url and auth == f"Bearer {SECRET}" for url, auth, _ in calls)
    if stage == "discovery":
        assert len(calls) == 1  # a stale discovery never starts another model request
    for role in (ModelRole.TUTOR_WRITER, ModelRole.PRACTICE_GENERATOR):
        provider = gateway.provider_for(role)
        assert provider is None if replacement == "delete" else provider.model == "model-b"


async def test_probe_copy_uses_captured_credential_even_if_store_rotates_before_resolver(tmp_path):
    service, gateway, store, _ = await configured(tmp_path)
    original_probe = gateway.probe_provider
    entered = asyncio.Event()
    release = asyncio.get_running_loop().create_future()
    seen = []
    async def delayed(provider, messages):
        entered.set()
        await release
        return await original_probe(provider, messages)
    gateway.probe_provider = delayed
    async def handler(request):
        seen.append(request.headers["authorization"])
        return chat()
    transport(gateway, handler)
    pending = asyncio.create_task(service.test_connection(operation_id="old"))
    await asyncio.wait_for(entered.wait(), 2)
    await service.apply_config(preset_id="custom", api_key="new-fake-key", base_url="https://new.invalid/v1", model="new")
    release.set_result(None)
    result = await pending
    assert seen == [f"Bearer {SECRET}"]
    assert not result.accepted and service.connection_status() == "configured"


@pytest.mark.parametrize("failure", ["write", "fsync", "replace"])
async def test_atomic_write_failure_keeps_old_json_and_reports_retry(tmp_path, monkeypatch, failure):
    service, gateway, store, path = await configured(tmp_path)
    old = path.read_bytes()
    original_fdopen = gateway_config.os.fdopen
    def broken(*_args, **_kwargs):
        raise OSError("simulated disk failure with private path")
    class PartialWrite:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *_args): self.stream.close()
        def write(self, text):
            self.stream.write(text[:8])
            raise OSError("disk full")
    with monkeypatch.context() as patch:
        if failure == "write":
            patch.setattr(gateway_config.os, "fdopen", lambda *args, **kwargs: PartialWrite(original_fdopen(*args, **kwargs)))
        else:
            patch.setattr(gateway_config.os, failure, broken)
        receipt = await service.apply_config(preset_id="custom", model="new-model", base_url="https://b.invalid/v1")
    assert receipt["persisted"] is False and receipt["persistence_error"] == "config_write_failed"
    assert gateway.provider_for(ModelRole.TUTOR_WRITER).model == "new-model"
    assert path.read_bytes() == old and json.loads(old)["model"] == "model-a"
    assert list(tmp_path.glob(".gateway.json.*.tmp")) == []
    retry = await service.apply_config(preset_id="custom", model="new-model", base_url="https://b.invalid/v1", expected_revision=receipt["revision"], expected_epoch=receipt["epoch"])
    assert retry["persisted"] is True and retry["persistence_error"] is None
    restored = GatewayConfigService(GenerativeModelGateway(store), store, path)
    assert restored.current_config()["model"] == "new-model"
    assert restored.revision() == retry["revision"]
    assert SECRET not in path.read_text()


async def test_restart_uses_durable_revision_but_rejects_previous_runtime_epoch(tmp_path):
    service, _, store, path = await configured(tmp_path)
    before = service.current_config()
    (tmp_path / ".gateway.json.interrupted.tmp").write_text('{"partial":')
    restarted = GatewayConfigService(GenerativeModelGateway(store), store, path)
    assert restarted.revision() == before["revision"]
    assert restarted.current_config()["epoch"] != before["epoch"]
    with pytest.raises(GatewayRevisionConflict):
        await restarted.apply_config(preset_id="custom", base_url="https://b.invalid", expected_revision=before["revision"], expected_epoch=before["epoch"])
    assert restarted.current_config()["model"] == "model-a"
    snapshot = restarted.current_config()
    snapshot["provider_configs"]["custom"]["model"] = "external mutation"
    assert restarted.current_config()["model"] == restarted.provider_profiles()["custom"]["model"] == "model-a"


async def test_api_receipts_expose_runtime_success_persistence_failure_and_stale_probe(tmp_path, monkeypatch):
    service, gateway, store, path = await configured(tmp_path)
    state = SimpleNamespace(gateway_config=service, secret_store=store, initial_assessment=None, refresh_model_writer=lambda: None)
    monkeypatch.setattr(desktop_api, "get_product_state", lambda: state)
    app = FastAPI()
    app.include_router(desktop_api.router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX)
    app.dependency_overrides[require_student_owner] = lambda: SimpleNamespace(student_id="owner")
    prefix = desktop_api.DESKTOP_ROUTER_PREFIX
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        before = (await client.get(prefix + "/settings")).json()
        with monkeypatch.context() as patch:
            patch.setattr(gateway_config.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("private path")))
            response = await client.put(prefix + "/settings", json={"preset_id": "custom", "model": "new", "base_url": "https://a.invalid/v1", "expected_revision": before["revision"], "expected_epoch": before["epoch"], "operation_id": "save-one"})
        assert response.status_code == 200
        saved = response.json()
        assert saved["accepted"] is True and saved["persisted"] is False and saved["persistence_error"] == "config_write_failed"
        assert saved["operation_id"] == "save-one" and saved["revision"] > before["revision"]
        assert "private path" not in response.text and SECRET not in response.text
        stale = await client.post(prefix + "/model/test", json={"revision": before["revision"], "epoch": before["epoch"], "operation_id": "probe-old"})
        assert stale.status_code == 200 and stale.json()["accepted"] is False and stale.json()["ok"] is False
        assert stale.json()["operation_id"] == "probe-old"
        retry = await client.put(prefix + "/settings", json={"preset_id": "custom", "model": "new", "base_url": "https://a.invalid/v1", "expected_revision": saved["revision"], "expected_epoch": saved["epoch"], "operation_id": "save-retry"})
        assert retry.json()["persisted"] is True and retry.json()["operation_id"] == "save-retry"
        rejected = await client.put(prefix + "/settings", json={"preset_id": "custom", "base_url": "https://b.invalid", "expected_revision": before["revision"], "expected_epoch": before["epoch"]})
        assert rejected.status_code == 409
        active = retry.json()
        durable_file = path.read_bytes()
        with monkeypatch.context() as patch:
            patch.setattr(gateway_config.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("skip disk failure")))
            skipped = await client.post(prefix + "/settings/onboarding/skip", json={"revision": active["revision"], "epoch": active["epoch"], "operation_id": "skip-failed"})
        assert skipped.status_code == 200
        assert skipped.json()["accepted"] is True and skipped.json()["persisted"] is False
        assert skipped.json()["operation_id"] == "skip-failed" and path.read_bytes() == durable_file
        skip_retry = await client.post(prefix + "/settings/onboarding/skip", json={"revision": skipped.json()["revision"], "epoch": active["epoch"], "operation_id": "skip-retry"})
        assert skip_retry.json()["persisted"] is True and skip_retry.json()["operation_id"] == "skip-retry"

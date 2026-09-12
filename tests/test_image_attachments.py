import asyncio
import base64
import json
import pytest
import httpx
from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import OpenAICompatibleProvider, OllamaProviderAdapter, ModelRole
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from mathtutor.infrastructure.vision import content_token_estimate, image_content, supports_vision, VISION_UNSUPPORTED
from mathtutor.repositories.image_repository import ImageRepository, MAX_IMAGE_BYTES, validate_image
from test_tutor_p0 import client_at, send, summary, count

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=")


def provider(calls, model="gpt-4.1", fail=False):
    async def key(): return "test-key-not-real"
    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(503 if fail else 200, json={"choices": [{"message": {"content": "先看等号两边：你在哪一步做了不同的运算？"}, "finish_reason": "stop"}]})
    return OpenAICompatibleProvider(base_url="https://example.invalid/v1", model=model, provider_id="openai", api_key_resolver=key, transport=httpx.MockTransport(transport))


def bind(calls, model="gpt-4.1", fail=False):
    state = get_product_state()
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider(calls, model, fail))
    state.controller.chat_responder = TutorChatResponder(state.gateway)


@pytest.mark.parametrize("text", ["", "这道题我为什么做错了？"])
def test_image_message_reaches_same_provider_and_survives_restart(tmp_path, text):
    db = tmp_path / "images.db"
    calls = []
    with client_at(db) as client:
        bind(calls)
        assert client.get("/api/v2/math-tutor/image-capabilities").json()["vision"]
        image = client.post("/api/v2/math-tutor/images", files={"file": ("题目.png", PNG, "image/png")})
        assert image.status_code == 201
        attachment = image.json()
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            frames = send(ws, "send_message", "image-1", {"text": text, "attachment_ids": [attachment["id"]]})
            assert any(f["event_type"] == "assistant_complete" for f in frames), frames
        body = calls[0]
        assert body["model"] == "gpt-4.1"
        parts = body["messages"][-1]["content"]
        assert parts[0]["type"] == "text" and (not text or parts[0]["text"] == text)
        assert parts[1]["type"] == "image_url"
        assert base64.b64decode(parts[1]["image_url"]["url"].split(",")[1]) == PNG
        messages = summary(client)["messages"]
        student = next(m for m in messages if m["role"] == "student")
        assert student["content"] == text
        assert student["attachments"] == [attachment]
        assert "base64" not in json.dumps(messages)
        assert count(db, "attempt_submissions") == 0
    with client_at(db) as client:
        assert next(m for m in summary(client)["messages"] if m["role"] == "student")["attachments"] == [attachment]
        restored = client.get(attachment["url"])
        assert restored.content == PNG and restored.headers["x-content-type-options"] == "nosniff"
        assert client.delete(attachment["url"]).status_code == 204
        assert client.get(attachment["url"]).status_code == 404


def test_unsupported_provider_never_ignores_image(tmp_path):
    calls = []
    with client_at(tmp_path / "db") as client:
        bind(calls, model="gpt-3.5-turbo")
        image = client.post("/api/v2/math-tutor/images", files={"file": ("a.png", PNG, "image/png")}).json()
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            frames = send(ws, "send_message", "unsupported", {"text": "你好", "attachment_ids": [image["id"]]})
        assert VISION_UNSUPPORTED in json.dumps(frames, ensure_ascii=False)
        assert not calls


def test_provider_failure_preserves_image_history(tmp_path):
    calls = []
    with client_at(tmp_path / "db") as client:
        bind(calls, fail=True)
        image = client.post("/api/v2/math-tutor/images", files={"file": ("a.png", PNG, "image/png")}).json()
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            frames = send(ws, "send_message", "failed", {"text": "解释", "attachment_ids": [image["id"]]})
        assert any(f["event_type"] == "assistant_error" for f in frames)
        assert summary(client)["messages"][0]["attachments"] == [image]
        assert client.get(image["url"]).content == PNG
        bind(calls)
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            retried = send(ws, "send_message", "failed", {"text": "解释", "attachment_ids": [image["id"]]})
            replay = send(ws, "send_message", "failed", {"text": "解释", "attachment_ids": [image["id"]]})
        assert any(f["event_type"] == "assistant_complete" for f in retried)
        assert len(calls) == 2
        assert len([m for m in summary(client)["messages"] if m["role"] == "student"]) == 1


@pytest.mark.parametrize("mime,data", [("application/pdf", b"%PDF"), ("image/svg+xml", b"<svg/>"), ("image/png", b"<html>"), ("image/jpeg", PNG), ("image/png", PNG + b"a" * MAX_IMAGE_BYTES)], ids=["pdf", "svg", "fake-png", "mime-mismatch", "oversize"])
def test_upload_validation(tmp_path, mime, data):
    with client_at(tmp_path / "db") as client:
        assert client.post("/api/v2/math-tutor/images", files={"file": ("a", data, mime)}).status_code == 400


@pytest.mark.asyncio
async def test_owner_count_and_deletion():
    repo = ImageRepository()
    image = await repo.put("one", PNG, "image/png", "a.png")
    assert await repo.get("two", image["id"]) is None
    with pytest.raises(ValueError): await repo.resolve("two", [image["id"]])
    with pytest.raises(ValueError): await repo.resolve("one", [image["id"]] * 5)
    await repo.remove("two", image["id"])
    assert await repo.get("one", image["id"])
    await repo.remove("one", image["id"])
    assert await repo.get("one", image["id"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("model,expected", [("gpt-4o-mini", True), ("gpt-4.1", True), ("gpt-4.1-2025-04-14", True), ("gpt-3.5-turbo", False), ("unknown", False)])
async def test_vision_capability(model, expected):
    assert await supports_vision(provider([], model)) is expected


@pytest.mark.asyncio
async def test_ollama_declared_vision_native_images_no_key():
    calls = []
    def transport(request):
        body = json.loads(request.content)
        if request.url.path == "/api/show": return httpx.Response(200, json={"capabilities": ["completion", "vision"]})
        calls.append(body)
        return httpx.Response(200, json={"message": {"content": "图片说明"}, "done_reason": "stop"})
    local = OllamaProviderAdapter(base_url="http://127.0.0.1:11434", model="local-custom", transport=httpx.MockTransport(transport))
    assert await supports_vision(local)
    await local.complete([{"role": "user", "content": image_content("题目", [{"data": PNG, "mime_type": "image/png"}])}])
    assert calls[0]["messages"][0]["images"] == [base64.b64encode(PNG).decode()]
    assert calls[0]["messages"][0]["content"] == "题目"


def test_large_base64_not_counted_as_text_tokens():
    content = image_content("解释", [{"data": b"a" * MAX_IMAGE_BYTES, "mime_type": "image/png"}])
    assert content_token_estimate(content) < 2000

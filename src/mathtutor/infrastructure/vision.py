"""Explicit provider capabilities and API-specific image content."""
import base64
import re

VISION_UNSUPPORTED = "当前配置未启用图片输入。若模型官方确认支持视觉，请到设置 → 高级选项 → 图片输入能力选择启用并保存。"


def openai_vision_model(provider_id, model):
    # Documented image-input families; unknown/custom aliases fail closed.
    if provider_id == "deepseek":
        return model in {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}
    if provider_id == "moonshot":
        return model in {"kimi-k2.5", "kimi-k2.6", "moonshot-v1-8k-vision-preview", "moonshot-v1-32k-vision-preview", "moonshot-v1-128k-vision-preview"}
    return provider_id == "openai" and bool(re.fullmatch(
        r"(?:gpt-4o(?:-mini)?|gpt-4\.1(?:-mini|-nano)?)(?:-\d{4}-\d{2}-\d{2})?", model))


async def supports_vision(provider):
    if provider is None or not getattr(provider, "model", ""):
        return False
    mode = getattr(provider, "vision_mode", "auto")
    if mode in {"enabled", "disabled"}:
        return mode == "enabled"
    capability = getattr(provider, "supports_vision", None)
    return bool(await capability()) if capability else False


def image_content(text, rows):
    return [{"type": "text", "text": text or "请帮助我理解这张图片中的题目。"}, *[
        {"type": "image_url", "image_url": {"url": f'data:{r["mime_type"]};base64,{base64.b64encode(r["data"]).decode("ascii")}', "detail": "auto"}}
        for r in rows]]


def ollama_messages(messages):
    result = []
    for message in messages:
        content = message.get("content", "")
        if not isinstance(content, list):
            result.append(dict(message))
            continue
        result.append({**message, "content": "\n".join(p["text"] for p in content if p.get("type") == "text"),
            "images": [p["image_url"]["url"].split(",", 1)[1] for p in content if p.get("type") == "image_url"]})
    return result


def content_token_estimate(content):
    if not isinstance(content, list):
        return len(str(content).encode("utf-8"))
    # Reserve a bounded image budget, never count encoded bytes as text tokens.
    return sum(1536 if p.get("type") == "image_url" else len(str(p.get("text", "")).encode("utf-8")) for p in content)

"""Explicit current-turn slash dispatch and bounded reference-only receipts.

No historical text, source document, repair prompt or model tool call enters
the dispatcher. The plugin service owns install/consent/runtime and its durable
execution ledger; this layer never executes code or decides learning facts.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re

SLASH = re.compile(r"^/([a-z][a-z0-9_-]{1,31})(?:\s|$)")
MAX_CONTEXT_BYTES = 12 * 1024


def parse_plugin_command(text: str) -> tuple[str, str] | None:
    match = SLASH.match(text)
    return (match[1], text[match.end():].strip()) if match else None


def slash_operation_id(owner: str, conversation_id: str, request_id: str) -> str:
    if not request_id:
        raise ValueError("A stable request identity is required")
    payload = json.dumps([owner, conversation_id, request_id], ensure_ascii=False, separators=(",", ":"))
    return "slash-" + sha256(payload.encode("utf-8")).hexdigest()


def format_plugin_receipt(context: dict) -> str:
    """Show actual data without requiring a provider or inventing an answer."""
    result = context.get("result", {})
    data = result.get("data", {})
    if isinstance(data, dict) and isinstance(data.get("text"), str) and data["text"].strip():
        body = data["text"].strip()
        other = {key: value for key, value in data.items() if key != "text"}
        if other:
            body += "\n\n```json\n" + json.dumps(other, ensure_ascii=False, indent=2, allow_nan=False) + "\n```"
    else:
        body = "```json\n" + json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n```"
    prefix = str(context.get("name") or "插件") + ("：没有可用记录。" if result.get("status") == "empty" else "运行结果：")
    partial = "\n\n这里只展示有界结果的一部分，完整结果请在插件页面查看。" if result.get("partial") else ""
    return prefix + "\n\n" + body + partial


def plugin_reference_context(record: dict, alias: str, receipt: dict) -> dict:
    plugin = record.get("plugin", {})
    value = {"command": alias, "plugin_id": plugin.get("id", ""), "name": plugin.get("name", alias),
             "execution": "already_executed_by_host", "authority": "reference_only", "result": receipt}
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_CONTEXT_BYTES:
        # Large real reports stay honest partial references. Never drop the
        # receipt silently or replace it with a fabricated successful answer.
        body = format_plugin_receipt(value)
        value["result"] = {"status": receipt.get("status", "ok"), "authority": "reference_only", "partial": True,
                           "data": {"text": body[:2000]}}
    return value

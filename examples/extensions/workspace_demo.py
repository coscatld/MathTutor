"""Offline creator SDK example: real scoped file I/O, no API key or model calls.

From the repository: python examples/extensions/workspace_demo.py
Install the project first with `python -m pip install -e .`.
"""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mathtutor.extensions import ExecutionContext
from mathtutor.extensions.builtin import default_registry
from mathtutor.extensions.workspaces import WorkspaceGrants


async def demo():
    with TemporaryDirectory(prefix="mathtutor-creator-demo-") as temporary:
        root = Path(temporary).resolve()
        grants = WorkspaceGrants()
        # This is an explicit HOST grant, never a model-callable operation.
        selected = grants.grant("demo-owner", str(root), writable=True)
        registry = default_registry(grants)
        context = ExecutionContext(owner_id="demo-owner", conversation_id="demo-conversation")
        executor = registry.bind(context, request_text="请在授权目录新建并保存 lesson.md 文件，再凭哈希更新这份笔记。")
        base = {"workspace_id": selected["workspace_id"], "relative_path": "lesson.md"}
        created = await executor.execute("ext_workspace_write_text", {**base, "content": "# 学习笔记\n先明确函数定义域。"}, "create")
        assert created["ok"], created
        read = await executor.execute("ext_workspace_read_text", base, "read")
        assert read["ok"] and "定义域" in read["result"]["text"], read
        updated = await executor.execute("ext_workspace_write_text", {**base,
            "content": read["result"]["text"] + "\n再检查端点。", "expected_hash": read["result"]["sha256"]}, "update")
        assert updated["ok"] and "检查端点" in (root / "lesson.md").read_text(encoding="utf-8"), updated
        grants.revoke("demo-owner", selected["workspace_id"])
        denied = await registry.bind(context).execute("ext_workspace_read_text", base, "revoked")
        assert not denied["ok"], denied
        print(json.dumps({"created": created["result"]["written"], "read": read["ok"],
                          "updated": updated["result"]["operation"], "revoked": denied["code"],
                          "authority": read["authority"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(demo())

import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";

test("new chat creates only a client draft and never POSTs an empty conversation", async () => {
  const source = await readFile(path.resolve(process.cwd(), "features/math-tutor/desktop/components/DesktopShell.tsx"), "utf8");
  const createBody = source.match(/const createConversation = \(\) => \{([\s\S]*?)\n  \};/)?.[1] ?? "";
  assert.ok(createBody.includes("makeSessionId()"));
  assert.ok(createBody.includes("router.push"));
  assert.ok(!createBody.includes("apiFetch"));
  assert.ok(!createBody.includes('method: "POST"'));
});

test("conversation history belongs to the shell and is not gated by the current route", async () => {
  const source = await readFile(path.resolve(process.cwd(), "features/math-tutor/desktop/components/DesktopShell.tsx"), "utf8");
  assert.ok(source.includes("!collapsed ? <div"));
  assert.ok(!source.includes("!collapsed && inTutor"));
});

test("sidebar footer contains Settings and no readiness status component", async () => {
  const source = await readFile(path.resolve(process.cwd(), "features/math-tutor/desktop/components/DesktopShell.tsx"), "utf8");
  assert.ok(source.includes('href="/math-tutor/settings"'));
  assert.ok(!source.includes("BootstrapStatus"));
  assert.ok(!source.includes("一切就绪"));
});

test("tooltip uses a portal and viewport collision padding", async () => {
  const source = await readFile(path.resolve(process.cwd(), "features/math-tutor/desktop/components/Tooltip.tsx"), "utf8");
  assert.ok(source.includes("createPortal"));
  assert.ok(source.includes("VIEWPORT_PADDING"));
  assert.ok(source.includes("onPointerEnter"));
  assert.ok(source.includes("max-w-[200px]"));
});

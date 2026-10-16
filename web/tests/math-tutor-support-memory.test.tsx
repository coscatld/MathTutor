import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { memoryAvailability, ToolMemoryCard } from "../features/math-tutor/components/TutorToolsPanel";
import type { DesktopMemory } from "../features/math-tutor/desktop/types";

const memory: DesktopMemory = { memory_id: "m", memory_type: "learning_preference", subject: "我", predicate: "内容", object_json: { value: "先解释定义，再带我推导" }, source_type: "USER_EXPLICIT", confidence: 1, retrieval_enabled: true, created_at: "2026-10-16", updated_at: "2026-10-16" };
const render = (entry: DesktopMemory) => renderToStaticMarkup(<ToolMemoryCard memory={entry} busy={false} onToggle={() => undefined} onConfirm={() => undefined} />);

test("conversation memory shows the actual value and an operable retrieval switch", () => {
  const html = render(memory);
  assert.ok(html.includes("先解释定义，再带我推导"));
  assert.ok(html.includes("我的记录"));
  assert.match(html, /type="checkbox"[^>]*checked/);
  assert.ok(!html.includes("已用于回答"));
});

test("disabled and unconfirmed memories do not claim they are eligible for answers", () => {
  const disabled = { ...memory, retrieval_enabled: false };
  assert.equal(memoryAvailability(disabled), "已停用");
  assert.ok(!/type="checkbox"[^>]*checked/.test(render(disabled)));
  const inferred = { ...memory, source_type: "MODEL_INFERRED" as const };
  assert.equal(memoryAvailability(inferred), "待你确认");
  const html = render(inferred);
  assert.ok(html.includes("确认这条记忆"));
  assert.ok(!html.includes('type="checkbox"'));
});

test("legacy predicate-only memories remain readable", () => {
  assert.ok(render({ ...memory, predicate: "请先给我一个例子", object_json: {} }).includes("请先给我一个例子"));
});

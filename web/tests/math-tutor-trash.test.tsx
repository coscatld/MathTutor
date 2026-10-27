import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ConversationDeleteDialog from "../features/math-tutor/desktop/components/ConversationDeleteDialog";
import ConversationTrashPanel from "../features/math-tutor/desktop/components/ConversationTrashPanel";

test("soft deletion explains local retention and exact trash path", () => {
  const html = renderToStaticMarkup(<ConversationDeleteDialog title="我的对话" onCancel={() => {}} onConfirm={async () => "deleted"} />);
  assert.ok(html.includes("本地记录不会删除"));
  assert.ok(html.includes("如果要彻底删除：设置&gt;垃圾桶"));
  assert.ok(html.includes("<dialog") && html.includes("aria-describedby"));
  assert.ok(html.includes("取消") && html.includes("移入垃圾桶"));
});
test("permanent deletion discloses scope and requires separate confirmation", () => {
  const html = renderToStaticMarkup(<ConversationDeleteDialog title="我的对话" permanent onCancel={() => {}} onConfirm={async () => "deleted"} />);
  assert.ok(html.includes("无法从垃圾桶恢复"));
  assert.ok(html.includes("其他对话共用的附件、学习记录与已有备份不会删除"));
});
test("trash initial render has a named section and loading feedback", () => {
  const html = renderToStaticMarkup(<ConversationTrashPanel />);
  assert.ok(html.includes("垃圾桶") && html.includes("正在加载垃圾桶"));
  assert.ok(html.includes('role="status"'));
});

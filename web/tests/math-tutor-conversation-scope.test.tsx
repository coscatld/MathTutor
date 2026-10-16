import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ConversationReferenceScope, { selectScopeLibraries, type ConversationScopeController } from "../features/math-tutor/components/ConversationReferenceScope";
import { mountConfiguration, type Mount } from "../features/math-tutor/knowledge/api";

const saved: Mount = {space_ids: ["course"], document_ids: ["lecture", "upload", "shared"], only_selected: true, mode: "tutor", save_space_id: "course", tool_mode: "structured", hints_only: true, available_documents: [
  {document_id: "lecture", title: "课程讲义", enabled: true, origin: "library", space_ids: ["course"]},
  {document_id: "upload", title: "本次题目", enabled: true, origin: "conversation", space_ids: []},
  {document_id: "shared", title: "共享公式", enabled: true, origin: "global", space_ids: []},
], effective_document_ids: ["lecture", "upload", "shared"]};

function controller(overrides: Partial<ConversationScopeController> = {}): ConversationScopeController {
  return {sessionId: "conversation", draft: saved, saved, libraries: [{space_id: "course", name: "数学课程", kind: "course", conversation_id: "", enabled: 1}, {space_id: "other", name: "另一对话专属资料", kind: "session", conversation_id: "other-conversation", enabled: 1}], status: "ready", previewing: false, previewError: "", error: "", saving: false, unconfirmed: false, notice: "", dirty: false, blocking: false, edit: () => undefined, save: async () => undefined, refresh: async () => undefined, ...overrides};
}

test("scope mutation payload preserves compatibility settings and excludes read-only document projections", () => {
  const payload = mountConfiguration(saved);
  assert.deepEqual(payload, {space_ids: ["course"], document_ids: ["lecture", "upload", "shared"], only_selected: true, mode: "tutor", save_space_id: "course", tool_mode: "structured", hints_only: true});
  assert.deepEqual(mountConfiguration({space_ids: [], document_ids: [], only_selected: true}), {space_ids: [], document_ids: [], only_selected: true, mode: "tutor", save_space_id: "", tool_mode: "native", hints_only: false});
});

test("removing a library drops its hidden whitelist IDs while retaining current uploads, globals and shared memberships", () => {
  const scope = {...saved, document_ids: [...saved.document_ids, "both"], available_documents: [...saved.available_documents!, {document_id: "both", title: "共同资料", enabled: true, origin: "library" as const, space_ids: ["course", "personal"]}]};
  assert.deepEqual(selectScopeLibraries(scope, ["personal"]).document_ids, ["upload", "shared", "both"]);
  assert.equal(selectScopeLibraries(scope, []).only_selected, true);
});

test("strict empty scope is explained and draft edits never claim to have applied", () => {
  const html = renderToStaticMarkup(<ConversationReferenceScope busy={false} controller={controller({draft: {...saved, document_ids: [], effective_document_ids: []}, dirty: true})} />);
  assert.match(html, /未勾选任何文档时，不参考文本资料/);
  assert.match(html, /尚未应用修改。当前仍使用已保存范围（3 份可检索资料）/);
  assert.match(html, /关闭面板会保留草案/);
  assert.doesNotMatch(html, /另一对话专属资料/);
  assert.match(html, /当前对话/);
  assert.match(html, /总资料/);
});

test("scope read failure cannot offer applying an invented empty default", () => {
  const html = renderToStaticMarkup(<ConversationReferenceScope busy={false} controller={controller({draft: null, saved: null, status: "failed", error: "参考范围读取失败"})} />);
  assert.match(html, /参考范围读取失败/);
  assert.match(html, /重新读取范围/);
  assert.doesNotMatch(html, /应用到当前对话/);
});

test("preview and unconfirmed writes disable applying, while image scope remains explicit", () => {
  for (const state of [{dirty: true, previewing: true}, {dirty: true, unconfirmed: true, blocking: true}]) {
    const html = renderToStaticMarkup(<ConversationReferenceScope busy={false} controller={controller(state)} />);
    assert.match(html, /<button[^>]*disabled=""[^>]*>[\s\S]*?应用到当前对话/);
    assert.match(html, /范围只控制文本检索，已发送图片由视觉模型读取/);
  }
});

import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {I18nProvider, translate} from "../lib/i18n";
import VaultFileList, {type VaultNote} from "../features/math-tutor/knowledge/VaultFileList";
import ReferenceJourney from "../features/math-tutor/knowledge/ReferenceJourney";
import {ResultView} from "../features/math-tutor/community/PluginWorkbench";
import {resultText} from "../features/math-tutor/community/result-export";
import {prepareDocuments} from "../features/math-tutor/community/imports";
import {type RunResult} from "../features/math-tutor/community/api";
import DocumentRow from "../features/math-tutor/desktop/components/DocumentRow";
import MemoryRow from "../features/math-tutor/desktop/components/MemoryRow";
import EmbeddingStatusBadge from "../features/math-tutor/desktop/components/EmbeddingStatusBadge";
import {documentResult} from "../features/math-tutor/desktop/lib/document-result";
import type {DesktopDocument, DesktopMemory, EmbeddingSettings} from "../features/math-tutor/desktop/types";

const noop = async () => undefined;
const en = (message: string, params?: Record<string, string | number>) => translate("en", message, params);
const render = (children: React.ReactNode) => renderToStaticMarkup(<I18nProvider initialLocale="en">{children}</I18nProvider>);
const document: DesktopDocument = {document_id: "doc", filename: "保存.md", mime_type: "text/markdown", status: "ready", retrieval_enabled: true, size_bytes: 100, page_count: 2, chunk_count: 3, image_count: 0, empty_page_count: 0, parse_warning: null, created_at: "2026-10-28T12:00:00Z", error: null, conversation_ids: ["a", "b"]};

test("knowledge SSR defaults to Chinese and supports English without translating file/tag data", () => {
  const note: VaultNote = {document_id: "note", title: "保存", tags: ["删除"], version: 2, links: [], editable: true, retrieval_enabled: true, provenance: {relative_path: "第一章/习题.md"}};
  const list = <VaultFileList notes={[note]} folder="" query="习题" name="我的笔记原名" busy={false} onFolder={() => undefined} onOpen={() => undefined} onToggle={() => undefined} />;
  assert.match(renderToStaticMarkup(list), /资料文件列表/);
  const html = render(list);
  assert.match(html, /aria-label="Resource file list"/); assert.match(html, /Markdown · Editable/);
  assert.match(html, /我的笔记原名/); assert.match(html, /第一章\/习题.md/); assert.match(html, /删除/);
  const journey = render(<ReferenceJourney />);
  assert.match(journey, /How sources inform answers/); assert.match(journey, /Choose references/);
});

test("desktop rows translate status, labels, and count templates while preserving user content", () => {
  const html = render(<DocumentRow document={document} busy={false} onToggleRetrieval={noop} onDelete={noop} onUpdated={() => undefined} />);
  assert.match(html, /3 chunks/); assert.match(html, /2 pages/); assert.match(html, /Available only in 2 linked conversations/);
  assert.match(html, /aria-label="Delete 保存.md"/); assert.match(html, /保存.md/);
  assert.doesNotMatch(html, /允许 Tutor 检索此资料/);
  assert.match(documentResult(document, en).description, /“保存.md”/);
  const memory: DesktopMemory = {memory_id: "memory", memory_type: "learning_preference", subject: "我", predicate: "内容", object_json: {value: "保存 删除：用户原文"}, source_type: "USER_EXPLICIT", confidence: 1, retrieval_enabled: true, created_at: "2026-10-28", updated_at: "2026-10-28"};
  const memoryHtml = render(<MemoryRow memory={memory} busy={false} onToggleRetrieval={noop} onDelete={noop} onConfirm={noop} onUpdated={() => undefined} />);
  assert.match(memoryHtml, /Learning preferences/); assert.match(memoryHtml, /My record/);
  assert.match(memoryHtml, /保存 删除：用户原文/); assert.match(memoryHtml, /Edit this memory/);
});

test("embedding status translates the known status rather than arbitrary server text", () => {
  const settings = {status: "local_ready", status_label: "本地模型就绪"} as EmbeddingSettings;
  assert.match(render(<EmbeddingStatusBadge settings={settings} />), /Local model ready/);
  assert.match(renderToStaticMarkup(<EmbeddingStatusBadge settings={settings} />), /本地模型就绪/);
});

test("plugin result UI and exported captions translate while model and problem content remain exact", () => {
  const result: RunResult = {schema_version: "mathtutor.community-result.v1", plugin_id: "test", plugin_version: "1", workflow: "exam-builder", status: "ok", read_only: true, authority: "reference_only", config: {}, limitations: [], teaching_guidance: "模型原文：保存", data: {title: "用户题库标题", requested_count: 1, actual_count: 1, seed: 0, answers_included: true, questions: [{id: "q", text: "解方程：2x=4，标签保存", point_title: "一元一次方程", grade: 7, reference_answer: "答案 x=2", explanation: "模型解释：删除"}]}};
  const html = render(<ResultView result={result} />);
  assert.match(html, /Selected 1 \/ requested 1 questions/); assert.match(html, /Reference answer and explanation/);
  for (const text of ["用户题库标题", "解方程：2x=4，标签保存", "一元一次方程", "答案 x=2", "模型解释：删除", "模型原文：保存"]) assert.ok(html.includes(text), text);
  const exported = resultText(result, en);
  assert.match(exported, /Reference answer: 答案 x=2/); assert.match(exported, /解方程：2x=4，标签保存/);
  assert.match(resultText(result), /参考答案：答案 x=2/);
});

test("import validation localizes UI errors without changing file paths", () => {
  assert.throws(() => prepareDocuments([], true, en), /This folder has no text documents/);
  assert.throws(() => prepareDocuments([], true), /这个文件夹没有可导入的文本资料/);
  const file = {name: "保存.md", webkitRelativePath: "学习/保存.md", size: 10, lastModified: 1};
  assert.equal(prepareDocuments([file], true, en).files[0], file);
});

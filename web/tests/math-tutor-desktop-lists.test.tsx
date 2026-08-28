import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import DocumentRow from "../features/math-tutor/desktop/components/DocumentRow";
import MemoryRow, { memoryObjectText } from "../features/math-tutor/desktop/components/MemoryRow";
import { DOCUMENT_STATUS_LABELS, MEMORY_TYPE_LABELS, memorySourceLabel } from "../features/math-tutor/desktop/lib/labels";
import type { DesktopDocument, DesktopMemory } from "../features/math-tutor/desktop/types";

function makeDocument(overrides: Partial<DesktopDocument> = {}): DesktopDocument {
  return {
    document_id: "doc-1",
    filename: "分数运算.md",
    mime_type: "text/markdown",
    status: "ready",
    retrieval_enabled: true,
    size_bytes: 2048,
    created_at: "2026-08-01T10:00:00Z",
    error: null,
    ...overrides,
  };
}

function makeMemory(overrides: Partial<DesktopMemory> = {}): DesktopMemory {
  return {
    memory_id: "mem-1",
    memory_type: "learning_preference",
    subject: "我",
    predicate: "喜欢",
    object_json: { value: "先看例题再动手" },
    source_type: "USER_EXPLICIT",
    confidence: 0.0,
    retrieval_enabled: true,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-01T10:00:00Z",
    ...overrides,
  };
}

const NOOP = async () => undefined;

test("DocumentRow: ready document renders public projection", () => {
  const html = renderToStaticMarkup(
    <DocumentRow
      document={makeDocument()}
      busy={false}
      onToggleRetrieval={NOOP}
      onDelete={NOOP}
      onUpdated={() => undefined}
    />,
  );
  assert.ok(html.includes("分数运算.md"), "shows filename");
  assert.ok(html.includes(DOCUMENT_STATUS_LABELS.ready), "shows status label");
  assert.ok(html.includes("2.0 KB"), "shows human-readable size");
  assert.ok(html.includes("2026-08-01"), "shows import date");
  assert.ok(html.includes("参与个性化回忆"), "shows retrieval toggle");
  assert.ok(!html.includes("重新解析"), "no reparse button for ready docs");
});

test("DocumentRow: failed document shows only the friendly error and a reparse action", () => {
  const doc = makeDocument({
    status: "failed",
    error: "无法解析此 PDF：文件可能已损坏。",
  });
  const html = renderToStaticMarkup(
    <DocumentRow document={doc} busy={false} onToggleRetrieval={NOOP} onDelete={NOOP} onUpdated={() => undefined} />,
  );
  assert.ok(html.includes("无法解析此 PDF：文件可能已损坏。"), "shows friendly error");
  assert.ok(html.includes("重新解析"), "offers reparse");
  for (const forbidden of ["storage_ref", "content_hash", "traceback", "Traceback"]) {
    assert.ok(!html.includes(forbidden), `no internal detail ${forbidden}`);
  }
});

test("MemoryRow: MODEL_INFERRED memory carries the AI badge and confirm button", () => {
  const memory = makeMemory({ source_type: "MODEL_INFERRED", confidence: 0.92 });
  const html = renderToStaticMarkup(
    <MemoryRow
      memory={memory}
      busy={false}
      onToggleRetrieval={NOOP}
      onDelete={NOOP}
      onConfirm={NOOP}
      onUpdated={() => undefined}
    />,
  );
  assert.ok(html.includes("AI 推测"), "shows AI badge");
  assert.ok(html.includes("92%"), "shows confidence");
  assert.ok(html.includes("确认"), "offers confirm (the only legal migration)");
});

test("MemoryRow: USER_EXPLICIT memory has no confirm button", () => {
  const html = renderToStaticMarkup(
    <MemoryRow
      memory={makeMemory()}
      busy={false}
      onToggleRetrieval={NOOP}
      onDelete={NOOP}
      onConfirm={NOOP}
      onUpdated={() => undefined}
    />,
  );
  assert.ok(html.includes("我的记录"), "shows explicit source label");
  assert.ok(html.includes("喜欢：先看例题再动手"), "shows predicate + value");
  assert.ok(!/确认/.test(html), "no confirm for explicit memories");
});

test("memoryObjectText: renders object_json.value or a compact key:value form", () => {
  assert.equal(memoryObjectText(makeMemory()), "先看例题再动手");
  assert.equal(memoryObjectText(makeMemory({ object_json: { value: "  " } })), "");
  assert.equal(memoryObjectText(makeMemory({ object_json: { a: 1, b: "x" } })), "a: 1，b: x");
  assert.equal(memoryObjectText(makeMemory({ object_json: {} })), "");
});

test("memory labels: all memory types map to friendly Chinese labels", () => {
  assert.equal(MEMORY_TYPE_LABELS.learning_preference, "学习偏好");
  assert.equal(MEMORY_TYPE_LABELS.ai_inference, "AI 推测");
  assert.equal(memorySourceLabel("MODEL_INFERRED"), "AI 推测");
  assert.equal(memorySourceLabel("UNKNOWN_SOURCE"), "UNKNOWN_SOURCE");
});

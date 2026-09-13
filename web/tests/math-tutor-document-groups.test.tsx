import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import DocumentGroups, { groupDocuments } from "../features/math-tutor/desktop/components/DocumentGroups";
import type { DesktopDocument } from "../features/math-tutor/desktop/types";

const docs = [
  {document_id:"a",filename:"私有.pdf",conversation_ids:["A","B"],conversation_titles:{A:"第一段对话",B:"第二段对话"}},
  {document_id:"b",filename:"总资料.pdf",is_global:true,conversation_ids:["A"]},
  {document_id:"c",filename:"未归类.pdf"},
] as DesktopDocument[];
test("files group by explicit scope and real conversation identity", () => {
  const groups = groupDocuments(docs);
  assert.equal(groups.global.length,1);
  assert.equal(groups.unassigned.length,1);
  assert.deepEqual(groups.conversations.map(g=>g.title),["第一段对话","第二段对话"]);
  assert.equal(groups.conversations[0].documents.length,1);
});
test("document library uses keyboard-accessible disclosure groups", () => {
  const html = renderToStaticMarkup(<DocumentGroups documents={docs} renderDocument={d=><li key={d.document_id}>{d.filename}</li>} />);
  assert.ok(html.includes("<details") && html.includes("<summary"));
  assert.ok(html.includes("总资料") && html.includes("对话资料") && html.includes("未归类"));
  assert.ok(html.includes("/math-tutor?session=A"));
});
test("image-only conversations remain visible without document records", () => {
  const grouped = groupDocuments([], [{conversation_id:"image-only",title:"图片对话"}]);
  assert.equal(grouped.conversations[0].title,"图片对话");
  assert.equal(grouped.conversations[0].documents.length,0);
});

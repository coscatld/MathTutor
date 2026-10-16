import test from "node:test";
import assert from "node:assert/strict";
import {communityView, documentPath, prepareDocuments} from "../features/math-tutor/community/imports";
const file = (name: string, size = 20, webkitRelativePath = "") => ({name, size, lastModified: 1, webkitRelativePath});

test("community keeps plugin links separate and routes former views to personal documents", () => {
  assert.equal(communityView("plugins"), "plugins");
  for (const tab of [null, "discover", "documents", "publish", "sources", "unknown"]) assert.equal(communityView(tab), "documents");
});

test("folder uploads preserve relative paths while excluding images and hidden configuration", () => {
  const selected = [file("函数.md", 20, "笔记/高一/函数.md"), file("复习.txt", 20, "笔记/复习.txt"), file("图.png", 20, "笔记/图.png"), file("config.md", 20, "笔记/.obsidian/config.md"), file(".DS_Store", 20, "笔记/.DS_Store")];
  const result = prepareDocuments(selected, true);
  assert.equal(result.skipped, 3);
  assert.deepEqual(result.files.map(documentPath), ["笔记/高一/函数.md", "笔记/复习.txt"]);
  assert.throws(() => prepareDocuments(selected.slice(2), true), /没有可导入的文本/);
});

test("document limits apply before upload and existing question packs must be selected alone", () => {
  assert.throws(() => prepareDocuments([file("large.txt", 1024 * 1024 + 1)]), /1 MB/);
  assert.throws(() => prepareDocuments(Array.from({length: 1001}, (_, index) => file(`${index}.md`))), /1000/);
  assert.throws(() => prepareDocuments(Array.from({length: 21}, (_, index) => file(`${index}.md`, 1024 * 1024))), /20 MB/);
  assert.throws(() => prepareDocuments([file("pack.mathtutor"), file("notes.md")]), /单独导入/);
  assert.throws(() => prepareDocuments([file("plugin.mtplugin")]), /学习笔记/);
  assert.equal(prepareDocuments([file("pack.mathtutor", 2 * 1024 * 1024)]).files.length, 1);
});

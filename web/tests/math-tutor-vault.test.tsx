import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import VaultFileList, { vaultEntries, vaultPath, type VaultNote } from "../features/math-tutor/knowledge/VaultFileList";

const notes: VaultNote[] = [
  { document_id: "a", title: "导数.md", version: 2, tags: ["单调性"], links: [], editable: true, retrieval_enabled: true, provenance: { relative_path: "高二/函数/导数.md" } },
  { document_id: "b", title: "圆锥曲线.md", version: 1, tags: [], links: [], editable: true, retrieval_enabled: true, provenance: { relative_path: "高二/圆锥曲线.md" } },
  { document_id: "c", title: "复习清单.md", version: 1, tags: [], links: [], editable: true, retrieval_enabled: false },
];

test("vault folders preserve imported hierarchy and show only direct children", () => {
  assert.deepEqual(vaultEntries(notes, "", "").folders, [{ name: "高二", path: "高二", count: 2 }]);
  assert.deepEqual(vaultEntries(notes, "", "").files.map(n => n.document_id), ["c"]);
  assert.deepEqual(vaultEntries(notes, "高二", "").files.map(n => n.document_id), ["b"]);
  assert.deepEqual(vaultEntries(notes, "高二/函数", "").files.map(n => n.document_id), ["a"]);
});

test("vault search includes paths and tags across folders without changing selection", () => {
  assert.deepEqual(vaultEntries(notes, "高二/函数", "圆锥").files.map(n => n.document_id), ["b"]);
  assert.deepEqual(vaultEntries(notes, "", "单调性").files.map(n => n.document_id), ["a"]);
  assert.equal(vaultPath({ ...notes[0], provenance: { relative_path: "../unsafe.md" } }), notes[0].title);
});

test("vault exposes each shared location and selects only the opened alias", () => {
  const shared = { ...notes[0], provenance: { ...notes[0].provenance, relative_paths: ["高二/函数/导数.md", "复习/导数复习.md"] } };
  assert.deepEqual(vaultEntries([shared], "复习", "").files.map(vaultPath), ["复习/导数复习.md"]);
  const html = renderToStaticMarkup(<VaultFileList notes={[shared]} folder="" query="导数" name="共享题库" selected="a" selectedPath="复习/导数复习.md" busy={false} onFolder={() => undefined} onOpen={() => undefined} onToggle={() => undefined} />);
  assert.equal((html.match(/aria-current="true"/g) || []).length, 1);
  assert.match(html, /共享正文（2 个位置）/);
  assert.match(html, /导数复习.md/);
});

test("vault renders accessible folder controls and keeps retrieval state distinct from selection", () => {
  const html = renderToStaticMarkup(<VaultFileList notes={notes} folder="" query="" name="共享题库" selected="c" busy={false} onFolder={() => undefined} onOpen={() => undefined} onToggle={() => undefined} />);
  assert.match(html, /资料文件夹路径/);
  assert.match(html, /高二/);
  assert.match(html, /检索已关/);
  assert.match(html, /aria-current="true"/);
});

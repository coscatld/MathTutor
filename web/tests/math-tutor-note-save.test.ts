import test from "node:test";
import assert from "node:assert/strict";
import { NoteSaveRejected, NoteSaveTracker, submitNote } from "../features/math-tutor/knowledge/note-save";

const identity = { libraryId: "library", documentId: "document", version: 3, previousPath: "旧目录/笔记.md" };
const fields = { title: "提交 A", body: "第一步\n第二步", tags: "函数， 草稿", relativePath: "新目录/笔记.md" };
function tracker() { let next = 0; return new NoteSaveTracker(() => `operation-${++next}`); }

test("submission captures exact title/body/path/tags and CAS before later edits", () => {
  const value = tracker(); value.edit();
  const snapshot = value.prepare(identity, fields);
  value.edit();
  assert.equal(value.unchanged(snapshot), false);
  assert.equal(snapshot.body, "第一步\n第二步"); assert.equal(snapshot.title, "提交 A");
  assert.equal(snapshot.tags, "函数， 草稿"); assert.equal(snapshot.relativePath, "新目录/笔记.md");
  assert.equal(snapshot.version, 3); assert.equal(snapshot.previousPath, "旧目录/笔记.md");
  assert.equal(Object.isFrozen(snapshot), true);
});

test("unknown outcome replays the original operation even after a new draft, then advances with a new ID", () => {
  const value = tracker(); value.edit();
  const first = value.prepare({ ...identity, documentId: null, version: null, previousPath: "" }, fields);
  value.edit();
  const newer = { ...fields, body: "后来输入 B", title: "标题 B", relativePath: "B.md", tags: "新标签" };
  assert.equal(value.prepare(identity, newer), first);
  assert.equal(value.pending?.body, fields.body);
  value.release(first);
  const second = value.prepare({ ...identity, version: 4, previousPath: fields.relativePath }, newer);
  assert.notEqual(second.operationId, first.operationId);
  assert.equal(second.body, newer.body); assert.equal(second.version, 4);
  assert.equal(second.previousPath, fields.relativePath);
});

test("same text after another edit still has a different editor revision", () => {
  const value = tracker(); value.edit(); const first = value.prepare(identity, fields);
  value.edit(); value.edit();
  assert.equal(value.unchanged(first), false);
});

test("switching documents invalidates old completions without releasing a newer operation", () => {
  const value = tracker(); const first = value.prepare(identity, fields);
  value.reset(); value.edit();
  const second = value.prepare({ ...identity, documentId: "another" }, { ...fields, body: "另一份笔记" });
  assert.equal(value.current(first), false); assert.equal(value.unchanged(first), false);
  value.release(first); assert.equal(value.pending, second);
});

test("write sends the captured snapshot and supports the backend's canonical path receipt", async () => {
  const original = global.fetch;
  try {
    global.fetch = async (_url, options) => {
      const payload = JSON.parse(options!.body as string);
      assert.deepEqual(payload, { title: fields.title, body: fields.body, tags: ["函数", "草稿"], operation_id: "operation-1",
        document_id: "document", expected_version: 3, relative_path: fields.relativePath, previous_relative_path: identity.previousPath });
      return Response.json({ document_id: "document", version: 4, relative_path: "新目录/笔记.md" });
    };
    assert.deepEqual(await submitNote(tracker().prepare(identity, fields)), { document_id: "document", version: 4, relative_path: "新目录/笔记.md" });
  } finally { global.fetch = original; }
});

test("explicit 4xx rejection can be corrected, while 5xx remains an unknown outcome", async () => {
  const original = global.fetch;
  try {
    for (const status of [409, 422, 500, 503]) {
      global.fetch = async () => Response.json({ detail: "fixture" }, { status });
      await assert.rejects(submitNote(tracker().prepare(identity, fields)), error => {
        assert.equal(error instanceof NoteSaveRejected, status < 500); return true;
      });
    }
  } finally { global.fetch = original; }
});

test("a malformed or regressing receipt never supplies a guessed CAS baseline", async () => {
  const original = global.fetch;
  try {
    for (const receipt of [{ document_id: "other", version: 4 }, { document_id: "document", version: 2 }, { document_id: "document", version: 0 }, { document_id: "document" }]) {
      global.fetch = async () => Response.json(receipt);
      await assert.rejects(submitNote(tracker().prepare(identity, fields)), /回执不完整/);
    }
  } finally { global.fetch = original; }
});

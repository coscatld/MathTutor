import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AttachmentStore, clipboardImages, deliverDraft, ingestPaste, ImageUploadRepository, MAX_IMAGE_BYTES, projectAttachments, validateImage } from "../features/math-tutor/lib/attachments";
import ImageAttachments from "../features/math-tutor/components/ImageAttachments";
import { initialMathTutorState, mathTutorReducer } from "../features/math-tutor/lib/reducer";

const file = (type = "image/png", size = 3) => new File([new Uint8Array(size)], "截图.png", { type });
function store() { let id = 0; const revoked: string[] = []; const value = new AttachmentStore({ createObjectURL: () => `blob:test-${++id}`, revokeObjectURL: u => revoked.push(u) }, () => `id-${id + 1}`); return { value, revoked }; }
const saved = { id: "550e8400-e29b-41d4-a716-446655440000", type: "image" as const, mimeType: "image/png", name: "图片", size: 3, url: "/api/v2/math-tutor/images/550e8400-e29b-41d4-a716-446655440000" };

for (const mode of ["Cmd+V", "Ctrl+V"]) test(`${mode} image uses paste event`, () => {
  const { value } = store(); let prevented = false;
  const data = { items: [{ kind: "file", getAsFile: () => file() }], getData: () => "" } as unknown as DataTransfer;
  ingestPaste(data, files => value.add(files), () => { prevented = true; });
  assert.equal(value.items.length, 1); assert.equal(prevented, true);
});
test("plain text paste is not intercepted", () => {
  const data = { items: [{ kind: "string", getAsFile: () => null }], getData: () => "文字" } as unknown as DataTransfer;
  ingestPaste(data, () => assert.fail(), () => assert.fail());
  assert.deepEqual(clipboardImages(data.items), []);
});
test("mixed clipboard retains default text insertion", () => {
  const { value } = store();
  const data = { items: [{ kind: "file", getAsFile: () => file() }], getData: () => "文字" } as unknown as DataTransfer;
  ingestPaste(data, files => value.add(files), () => assert.fail()); assert.equal(value.items.length, 1);
});
for (const type of ["image/png", "image/jpeg", "image/webp"]) test(`upload accepts ${type}`, () => { assert.equal(validateImage(file(type), 0), null); });
test("reject pdf svg oversize empty and fifth file", () => {
  for (const bad of [file("application/pdf"), file("image/svg+xml"), file("image/png", MAX_IMAGE_BYTES + 1), file("image/png", 0)]) assert.ok(validateImage(bad, 0));
  const { value } = store(); assert.equal(value.add(Array.from({ length: 5 }, () => file())).length, 1); assert.equal(value.items.length, 4);
});
test("drop and upload wire to the same addFiles function", () => {
  const hook = readFileSync("features/math-tutor/hooks/useChatAttachments.ts", "utf8");
  const composer = readFileSync("features/math-tutor/components/ChatComposer.tsx", "utf8");
  assert.match(hook, /addFiles\(Array.from\(event.dataTransfer.files\)\)/);
  assert.match(composer, /images.addFiles\(Array.from\(event.target.files/);
  assert.doesNotMatch(hook, /keydown|localStorage|alert\(/);
});
test("remove only revokes matching object URL; unmount cleanup revokes remainder", () => {
  const { value, revoked } = store(); value.add([file(), file()]); value.remove(value.items[0].id);
  assert.equal(revoked.length, 1); assert.equal(value.items.length, 1); value.clear(); value.clear(); assert.equal(revoked.length, 2);
});
test("text and image send as one draft and clear only after success", async () => {
  const { value, revoked } = store(); value.add([file()]); let text = "说明";
  let finish!: (result: boolean) => void;
  const pending = deliverDraft(text, value.items, async (sent, files) => { assert.equal(sent, text); assert.equal(files.length, 1); return new Promise(resolve => { finish = resolve; }); }, () => { text = ""; value.clear(); });
  assert.equal(value.items.length, 1); finish(true); assert.equal(await pending, true); assert.equal(text, ""); assert.equal(revoked.length, 1);
});
test("image-only allowed; empty message not sent", async () => {
  const { value } = store(); value.add([file()]);
  assert.equal(await deliverDraft("", value.items, async (text, images) => !text && images.length === 1, () => value.clear()), true);
  assert.equal(await deliverDraft("", [], async () => { assert.fail(); }, () => assert.fail()), false);
});
test("failed send and thrown API request retain text and image for retry", async () => {
  const { value } = store(); value.add([file()]);
  assert.equal(await deliverDraft("文字", value.items, async () => false, () => assert.fail()), false);
  await assert.rejects(deliverDraft("文字", value.items, async () => { throw Error("offline"); }, () => assert.fail()));
  assert.equal(value.items.length, 1);
});
test("history preserves image-only message and rejects arbitrary URL or malformed fields", () => {
  const next = mathTutorReducer(initialMathTutorState("s"), { type: "restore", summary: { messages: [{ role: "student", content: "", attachments: [saved] }] } });
  assert.equal(next.messages.length, 1); assert.deepEqual(next.messages[0].attachments, [saved]);
  assert.deepEqual(projectAttachments([null, "oops", { type: "image", id: "../../secret" }]), []);
  assert.equal(projectAttachments([{ ...saved, url: "https://evil.invalid" }])[0].url, saved.url);
});
test("no empty preview space; thumbnails have accessible zoom and delete", () => {
  assert.equal(renderToStaticMarkup(<ImageAttachments images={[]} />), "");
  const html = renderToStaticMarkup(<ImageAttachments images={[saved]} onRemove={() => {}} />);
  assert.match(html, /放大图片/); assert.match(html, /删除图片/); assert.match(html, /object-contain/); assert.match(html, /<dialog/);
});
test("vision=false prevents upload; successful upload is reused on retry", async () => {
  const original = global.fetch; let vision = false; let uploads = 0;
  global.fetch = async input => {
    if (String(input).endsWith("image-capabilities")) return Response.json({ vision });
    uploads++; return Response.json(saved, { status: 201 });
  };
  try {
    const repo = new ImageUploadRepository(); const { value } = store(); value.add([file()]);
    await assert.rejects(repo.upload(value.items), /未启用图片输入/); assert.equal(uploads, 0);
    vision = true; assert.deepEqual(await repo.upload(value.items), [saved]); await repo.upload(value.items); assert.equal(uploads, 1);
  } finally { global.fetch = original; }
});

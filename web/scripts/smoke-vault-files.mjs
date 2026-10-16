// File-manager UI acceptance with synthetic, mutable API fixtures. The real
// archive parser/versioning tests live in the backend suite. No model is called.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.LAYOUT_URL || "http://localhost:3197";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-vault-files-"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
await page.emulateMedia({ reducedMotion: "reduce" });
const errors = [], mutations = [], screenshots = [];
page.on("pageerror", error => errors.push(error.message));
const library = { space_id: "fixture-vault", name: "我的数学笔记", kind: "course", conversation_id: "", enabled: 1 };
const importedLibrary = { space_id: "fixture-shared", name: "共享运算题库", kind: "course", conversation_id: "", enabled: 1 };
let libraries = [library];
const shared = { document_id: "shared-function", title: "函数.md", body: "# 函数\n先检查定义域。", version: 2, paths: ["高一/函数.md", "复习/函数.md"], tags: ["函数"], retrieval_enabled: true };
const derivative = { document_id: "derivative", title: "导数.md", body: "# 导数\n检查端点与驻点。", version: 1, paths: ["高二/导数.md"], tags: ["导数"], retrieval_enabled: true };
const imported = { document_id: "shared-sum", title: "加法.md", body: "# 加法\n\n题目：2+3=?\n\n用户参考答案：5。\n\n未经应用自动数学核验。", version: 1, paths: ["题目/加法.md"], tags: ["小学"], retrieval_enabled: true };
const byLibrary = id => id === importedLibrary.space_id ? [imported] : [shared, derivative];
const projection = doc => ({ document_id: doc.document_id, title: doc.title, version: doc.version, tags: doc.tags, links: [], retrieval_enabled: doc.retrieval_enabled, editable: true,
  provenance: { format: "markdown", relative_path: doc.paths[0], relative_paths: [...doc.paths], vault_paths: { [library.space_id]: doc.paths.map(relative => ({ path: relative, title: doc.title, tags: doc.tags })) } } });
const source = doc => ({ ...projection(doc), body: doc.body, body_hash: createHash("sha256").update(doc.body).digest("hex"), backlinks: [] });
let lastExport;

// A small stored ZIP fixture keeps downloaded bytes honest without a ZIP npm
// dependency. Its entries contain the edited text and a real SHA-256 manifest.
function zip(entries) {
  const locals = [], central = []; let offset = 0;
  for (const [name, text] of entries) {
    const filename = Buffer.from(name), data = Buffer.from(text); let crc = 0xffffffff;
    for (const byte of data) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0); }
    crc = (crc ^ 0xffffffff) >>> 0;
    const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20, 4); local.writeUInt16LE(0x800, 6); local.writeUInt32LE(crc, 14); local.writeUInt32LE(data.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(filename.length, 26);
    const header = Buffer.alloc(46); header.writeUInt32LE(0x02014b50); header.writeUInt16LE(20, 4); header.writeUInt16LE(20, 6); header.writeUInt16LE(0x800, 8); header.writeUInt32LE(crc, 16); header.writeUInt32LE(data.length, 20); header.writeUInt32LE(data.length, 24); header.writeUInt16LE(filename.length, 28); header.writeUInt32LE(offset, 42);
    locals.push(local, filename, data); central.push(header, filename); offset += local.length + filename.length + data.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}
await page.route("**/api/**", async route => {
  const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method();
  let body = [];
  if (pathname.endsWith("/auth/status")) body = { enabled: false, authenticated: true };
  else if (pathname.endsWith("/bootstrap")) body = { phase: "READY", readiness: "READY", steps: [] };
  else if (pathname.endsWith("/settings")) body = { is_configured: true, onboarding_completed: true, preset_id: "local", model: "fixture", base_url: "http://127.0.0.1", key_masked: null, provider_configs: {} };
  else if (pathname.endsWith("/knowledge/libraries")) body = libraries;
  else if (pathname.endsWith("/knowledge/drafts")) body = [];
  else if (/\/knowledge\/libraries\/[^/]+\/notes$/.test(pathname)) {
    const id = pathname.split("/").at(-2);
    if (method === "POST") {
      const input = request.postDataJSON(), doc = byLibrary(id).find(item => item.document_id === input.document_id);
      assert.ok(doc); assert.equal(input.expected_version, doc.version); assert.ok(input.operation_id);
      assert.equal(input.previous_relative_path, "复习/函数.md", "moving an alias must identify the opened path");
      assert.ok(doc.paths.includes(input.previous_relative_path));
      doc.paths = doc.paths.map(relative => relative === input.previous_relative_path ? input.relative_path : relative);
      doc.body = input.body; doc.title = input.title; doc.tags = input.tags; doc.version++;
      mutations.push({ kind: "save", ...input }); body = { document_id: doc.document_id };
    } else body = byLibrary(id).map(projection);
  } else if (/\/knowledge\/sources\/[^/]+$/.test(pathname)) {
    const doc = [shared, derivative, imported].find(item => item.document_id === pathname.split("/").at(-1));
    assert.ok(doc); body = source(doc);
  } else if (/\/documents\/[^/]+\/retrieval$/.test(pathname)) {
    const doc = [shared, derivative, imported].find(item => item.document_id === pathname.split("/").at(-2));
    assert.ok(doc); doc.retrieval_enabled = request.postDataJSON().enabled; mutations.push({ kind: "retrieval", id: doc.document_id, enabled: doc.retrieval_enabled }); body = projection(doc);
  } else if (pathname.endsWith("/content/question-packs/import")) {
    assert.equal(method, "POST"); assert.match(request.postDataBuffer().toString("utf8"), /mathtutor\.question-pack\.v1/);
    libraries = [...libraries, importedLibrary]; mutations.push({ kind: "import" }); body = { space_id: importedLibrary.space_id, name: importedLibrary.name, imported_count: 1, warnings: [], format: "mathtutor.question-pack.v1" };
  } else if (/\/content\/libraries\/[^/]+\/export$/.test(pathname)) {
    const id = pathname.split("/").at(-2), docs = byLibrary(id), files = docs.flatMap(doc => doc.paths.map(relative => ({ path: relative, title: doc.title, tags: doc.tags, sha256: createHash("sha256").update(doc.body).digest("hex"), source_format: "markdown", body: doc.body })));
    lastExport = zip([...files.map(file => [file.path, file.body]), ["manifest.json", JSON.stringify({ format: "mathtutor.vault.v1", name: libraries.find(item => item.space_id === id).name, files: files.map(({body: _body, ...metadata}) => metadata) })]]);
    mutations.push({ kind: "export", id, paths: files.map(file => file.path) });
    return route.fulfill({ contentType: "application/zip", headers: { "Content-Disposition": 'attachment; filename="fixture-vault.zip"' }, body: lastExport });
  }
  await route.fulfill({ json: body });
});
await page.routeWebSocket("**/api/**", () => {});
const list = page.getByRole("list", { name: "资料文件列表", exact: true });
const rootFolder = () => page.getByRole("navigation", { name: "资料文件夹路径", exact: true }).getByRole("button", { name: library.name, exact: true }).click();
const capture = async name => { assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "vault cannot overflow horizontally"); await page.screenshot({ path: path.join(output, `${name}.png`), animations: "disabled" }); screenshots.push({ name, viewport: page.viewportSize() }); };
const exportCurrent = async name => {
  const options = page.locator("details").filter({ has: page.getByText("知识库选项", { exact: true }) });
  if (!await options.evaluate(node => node.open)) await options.locator("summary").click();
  const pending = page.waitForEvent("download"); await page.getByRole("button", { name: "导出共享资料库", exact: true }).click();
  const download = await pending, filename = path.join(output, name); await download.saveAs(filename);
  assert.deepEqual(await readFile(filename), lastExport); return lastExport;
};
try {
  await page.goto(`${base}/math-tutor/knowledge?conversation=vault-fixture`);
  await page.locator(".mt-library-choice").filter({ hasText: library.name }).click();
  await list.getByRole("button", { name: /^复习/ }).click();
  await list.locator(".mt-note-open").first().click();
  const position = page.getByRole("textbox", { name: /^文件位置/ });
  await page.waitForFunction(() => Array.from(document.querySelectorAll("input")).some(input => input.value === "复习/函数.md"));
  assert.equal(await position.inputValue(), "复习/函数.md", "opening an alias selects its actual path rather than the first path");
  await position.fill("归档/函数复习.md");
  const edited = "# 函数复习\n先检查定义域，再讨论单调性。";
  await page.getByRole("textbox", { name: "Markdown 正文", exact: true }).fill(edited);
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  await page.getByText("笔记已保存，可在显式挂载此库的会话中检索。", { exact: true }).waitFor();
  assert.deepEqual(shared.paths, ["高一/函数.md", "归档/函数复习.md"]);
  assert.equal(shared.body, edited); assert.equal(mutations.filter(item => item.kind === "save").length, 1);
  console.log("checked alias-move-and-shared-body-save");
  await rootFolder();
  await list.getByRole("button", { name: /^高一/ }).click();
  await list.locator(".mt-note-open").first().click();
  await page.waitForFunction(() => Array.from(document.querySelectorAll("input")).some(input => input.value === "高一/函数.md"));
  assert.equal(await position.inputValue(), "高一/函数.md");
  assert.equal(await page.getByRole("textbox", { name: "Markdown 正文", exact: true }).inputValue(), edited, "aliases share the edited document body");
  await page.getByRole("textbox", { name: "按标题、文件夹或标签筛选", exact: true }).fill("函数");
  await page.waitForFunction(() => document.querySelectorAll(".mt-note-open").length === 2);
  await list.getByRole("button", { name: /的检索$/ }).first().click();
  await list.getByText("检索已关", { exact: true }).first().waitFor();
  assert.equal(await list.getByText("检索已关", { exact: true }).count(), 2, "retrieval preference belongs to the shared document");
  await list.getByRole("button", { name: /的检索$/ }).first().click();
  await list.getByText("检索已开", { exact: true }).first().waitFor();
  console.log("checked shared-document-retrieval-toggle");
  const editedZip = await exportCurrent("edited-vault.zip");
  assert.ok(editedZip.includes(Buffer.from(edited))); assert.ok(editedZip.includes(Buffer.from("归档/函数复习.md"))); assert.ok(editedZip.includes(Buffer.from("高一/函数.md")));
  console.log("checked edited-vault-export");
  await page.setViewportSize({ width: 375, height: 812 });
  await position.scrollIntoViewIfNeeded(); await capture("vault-editor-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const chosen = page.waitForEvent("filechooser"); await page.getByRole("button", { name: "导入共享题库", exact: true }).click();
  await (await chosen).setFiles({ name: "shared-sum.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({ format: "mathtutor.question-pack.v1", name: importedLibrary.name, questions: [{ id: "sum", stem: "2+3=?", answer: "5", grade: 1 }] })) });
  await page.getByText("已导入 1 份可编辑资料。尚未加入当前对话的参考范围。", { exact: true }).waitFor();
  assert.equal(await page.getByRole("textbox", { name: "按标题、文件夹或标签筛选", exact: true }).inputValue(), "", "importing a new library clears the previous library's search");
  await list.getByRole("button", { name: /^题目/ }).click();
  await list.locator(".mt-note-open").first().click();
  await page.waitForFunction(() => document.querySelector("textarea")?.value.includes("用户参考答案"));
  const importedZip = await exportCurrent("imported-vault.zip"); assert.ok(importedZip.includes(Buffer.from("用户参考答案")));
  await page.locator("#workspace-content").evaluate(node => node.scrollTo(0, 0)); await capture("vault-import-desktop");
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({ status: "PASS", mocked_traffic: true, paid_model_calls: 0, mutations, screenshots, page_errors: errors }, null, 2));
  console.log(JSON.stringify({ status: "PASS", output, paid_model_calls: 0 }));
} finally { await browser.close(); }

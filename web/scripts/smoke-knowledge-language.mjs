// Actual editor regression: a UI language change must not reload or reset a dirty note.
import assert from "node:assert/strict";
import {mkdtemp, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({executablePath: process.env.CHROME_EXECUTABLE, headless: true});
const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
page.setDefaultTimeout(15000);
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-knowledge-language-"));
const reads = [], writes = [], errors = [], confirms = [];
let document = {document_id: "note", version: 1, title: "用户的原始标题", tags: ["原标签"], body: "用户的原始正文", path: "原路径.md"};
const note = () => ({document_id: document.document_id, version: document.version, title: document.title, tags: document.tags,
  links: [], editable: true, retrieval_enabled: true, provenance: {format: "markdown", relative_path: document.path, relative_paths: [document.path], library_paths: [{path: document.path, title: document.title, tags: document.tags}]}});
page.on("pageerror", error => errors.push(error.message));
page.on("dialog", dialog => {confirms.push(dialog.message()); void dialog.accept();});
await page.route("**/api/**", async route => {
  const request = route.request(), pathname = new URL(request.url()).pathname;
  const reply = json => route.fulfill({json});
  if (request.method() === "GET") reads.push(pathname);
  if (pathname.endsWith("/auth/status")) return reply({enabled: false, authenticated: true});
  if (pathname.endsWith("/bootstrap")) return reply({phase: "READY", readiness: "READY", steps: []});
  if (pathname.endsWith("/settings")) return reply({is_configured: true, onboarding_completed: true, provider_configs: {}});
  if (pathname.endsWith("/knowledge/libraries")) return reply([{space_id: "lib", name: "用户知识库名字", kind: "personal", enabled: 1, conversation_id: ""}]);
  if (pathname.endsWith("/knowledge/drafts")) return reply([]);
  if (pathname.endsWith("/knowledge/libraries/lib/notes")) {
    if (request.method() === "GET") return reply([note()]);
    const input = request.postDataJSON(); writes.push(input);
    assert.equal(input.expected_version, document.version);
    assert.equal(input.previous_relative_path, document.path);
    document = {...document, version: document.version + 1, title: input.title, body: input.body, tags: input.tags, path: input.relative_path};
    return reply({document_id: document.document_id, version: document.version, relative_path: document.path});
  }
  if (pathname.endsWith("/knowledge/sources/note")) return reply({...note(), body: document.body, body_hash: "fixture", backlinks: []});
  return reply([]);
});
const chooseLocale = async locale => {
  // The same local event used by the public language picker; no reload or navigation.
  await page.evaluate(locale => {localStorage.setItem("mathtutor-language", locale); window.dispatchEvent(new Event("mathtutor-language-change"));}, locale);
};
try {
  await page.goto(`${process.env.LAYOUT_URL || "http://127.0.0.1:3198"}/math-tutor/knowledge?library=lib&source=note`);
  await page.waitForFunction(() => document.querySelector('input[maxlength="512"]')?.value === "原路径.md");
  const draft = {title: "知识库 保存：我的标题", body: "未保存：保存 删除 x²，用户正文保持原样", tags: "删除, English tag", path: "第一章/保存.md", filter: "用户"};
  await page.getByRole("textbox", {name: "笔记标题", exact: true}).fill(draft.title);
  await page.getByRole("textbox", {name: "Markdown 正文", exact: true}).fill(draft.body);
  await page.getByRole("textbox", {name: /^标签/}).fill(draft.tags);
  await page.getByRole("textbox", {name: /^文件位置/}).fill(draft.path);
  await page.getByRole("textbox", {name: "按标题、文件夹或标签筛选", exact: true}).fill(draft.filter);
  await page.waitForTimeout(150);
  const readsBefore = reads.length;
  await chooseLocale("en");
  await page.getByRole("heading", {name: "Knowledge library", exact: true}).waitFor();
  for (const [name, value] of [["Note title", draft.title], ["Markdown content", draft.body], ["Tags(comma-separated)", draft.tags], ["File location", draft.path], ["Filter by title, folder, or tag", draft.filter]]) {
    const field = name === "Tags(comma-separated)" ? page.getByRole("textbox", {name: /^Tags/}) : name === "File location" ? page.getByRole("textbox", {name: /^File location/}) : page.getByRole("textbox", {name, exact: true});
    assert.equal(await field.inputValue(), value);
  }
  await page.getByText("Unsaved", {exact: true}).waitFor();
  assert.equal(await page.getByRole("button", {name: "Save new version", exact: true}).isEnabled(), true);
  await page.waitForTimeout(150); assert.equal(reads.length, readsBefore, "language changes do not trigger note or library reloads");
  await page.screenshot({path: path.join(output, "english-dirty-note.png"), fullPage: true});
  await page.setViewportSize({width: 375, height: 1000});
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "English knowledge page fits a 375px viewport");
  await page.screenshot({path: path.join(output, "english-dirty-note-375.png"), fullPage: true});
  await page.setViewportSize({width: 1440, height: 1100});
  await page.getByRole("button", {name: "Save new version", exact: true}).click();
  await page.getByRole("status").filter({hasText: "Note saved as v2"}).waitFor();
  assert.equal(writes.length, 1); assert.equal(writes[0].body, draft.body); assert.equal(writes[0].title, draft.title);
  assert.equal(writes[0].relative_path, draft.path); assert.deepEqual(writes[0].tags, ["删除", "English tag"]);
  assert.equal(writes[0].expected_version, 1); assert.match(confirms[0], /Save as v2/);
  const readsAfterSave = reads.length;
  await chooseLocale("zh-CN");
  await page.getByRole("heading", {name: "知识库", exact: true}).waitFor();
  await page.getByRole("status").filter({hasText: "笔记已保存为 v2"}).waitFor();
  assert.equal(await page.getByRole("textbox", {name: "Markdown 正文", exact: true}).inputValue(), draft.body);
  await page.waitForTimeout(150); assert.equal(reads.length, readsAfterSave);
  assert.deepEqual(errors, []);
  await page.screenshot({path: path.join(output, "chinese-saved-note.png"), fullPage: true});
  await writeFile(path.join(output, "results.json"), JSON.stringify({checks: ["dirty fields/filter preserved", "no locale-triggered requests", "one save retains original CAS/path/data", "English confirm and receipt", "switch back preserves content"], reads, writes, confirms, errors}, null, 2));
  console.log(`PASS knowledge language interaction; evidence: ${output}`);
} catch (error) {await page.screenshot({path: path.join(output, "failure.png"), fullPage: true}); console.error(`Evidence: ${output}`); throw error;}
finally {await browser.close();}

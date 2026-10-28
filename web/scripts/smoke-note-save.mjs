// Actual React editor interactions with delayed/failed local API fixtures. No model calls.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
page.setDefaultTimeout(15000);
const base = process.env.LAYOUT_URL || "http://127.0.0.1:3198";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-note-save-"));
const checks = [], errors = [], writes = [], ledger = new Map();
page.on("pageerror", error => errors.push(error.message));
const library = { space_id: "lib", name: "数学笔记", kind: "course", enabled: 1, conversation_id: "" };
const otherLibrary = { ...library, space_id: "lib-other", name: "另一知识库" };
const docs = [
  { id: "old", version: 1, body: "原笔记正文", paths: [{ path: "old.md", title: "old.md", tags: ["原标签"] }] },
  { id: "other", version: 1, body: "另一份文档正文", paths: [{ path: "other.md", title: "other.md", tags: ["另一个标签"] }] },
];
let postGate, sourceGate, failSource = false, failList = false, nextOutcome = "ok", nextId = 0, allowLeave = false, leaveConfirmations = 0;
const projection = doc => ({ document_id: doc.id, title: doc.paths[0].title, version: doc.version, tags: doc.paths[0].tags, links: [], editable: true, retrieval_enabled: true,
  provenance: { format: "markdown", relative_path: doc.paths[0].path, relative_paths: doc.paths.map(item => item.path), library_paths: doc.paths.map(item => ({ ...item })) } });
const source = doc => ({ ...projection(doc), body: doc.body, body_hash: createHash("sha256").update(doc.body).digest("hex"), backlinks: [] });
page.on("dialog", dialog => {
  if (dialog.message().includes("笔记有未保存修改")) { leaveConfirmations++; void (allowLeave ? dialog.accept() : dialog.dismiss()); }
  else void dialog.accept();
});
await page.route("**/api/**", async route => {
  const request = route.request(), pathname = new URL(request.url()).pathname;
  const reply = (json, status = 200) => route.fulfill({ json, status });
  if (pathname.endsWith("/auth/status")) return reply({ enabled: false, authenticated: true });
  if (pathname.endsWith("/bootstrap")) return reply({ phase: "READY", readiness: "READY", steps: [] });
  if (pathname.endsWith("/settings")) return reply({ is_configured: true, onboarding_completed: true, provider_configs: {} });
  if (pathname.endsWith("/knowledge/libraries")) return reply([library, otherLibrary]);
  if (pathname.endsWith("/knowledge/drafts")) return reply([]);
  if (pathname.endsWith("/knowledge/libraries/lib-other/notes")) {
    await new Promise(resolve => setTimeout(resolve, 180));
    const doc = docs.find(item => item.id === "old");
    return reply([{ ...projection(doc), title: "另一库标题.md", tags: ["另一库标签"], provenance: { format: "markdown", relative_path: "另一库/共享.md", relative_paths: ["另一库/共享.md"], library_paths: [{ path: "另一库/共享.md", title: "另一库标题.md", tags: ["另一库标签"] }] } }]);
  }
  if (pathname.endsWith("/knowledge/libraries/lib/notes")) {
    if (request.method() !== "POST") return reply(failList ? { detail: "列表暂时离线" } : docs.map(projection), failList ? 503 : 200);
    const input = request.postDataJSON(); writes.push(structuredClone(input));
    const previous = ledger.get(input.operation_id);
    if (previous) { assert.deepEqual(input, previous.input); return reply(previous.receipt); }
    const outcome = nextOutcome; nextOutcome = "ok";
    if (outcome === "reject") return reply({ detail: "版本冲突，不能覆盖旧版本。" }, 409);
    let doc = input.document_id ? docs.find(item => item.id === input.document_id) : docs.find(item => item.body === input.body);
    const savedPath = input.relative_path.replaceAll("\\", "/") || `${input.title.replace(/\.md$/, "")}.md`;
    const location = { path: savedPath, title: `${input.title.replace(/\.md$/, "")}.md`, tags: input.tags };
    if (input.document_id) {
      assert.ok(doc);
      if (input.expected_version !== doc.version) return reply({ detail: "版本冲突，不能覆盖旧版本。" }, 409);
      const index = doc.paths.findIndex(item => item.path === input.previous_relative_path);
      assert.ok(index >= 0, "rename starts at the last confirmed path");
      doc.paths[index] = location; doc.body = input.body; doc.version++;
    } else if (doc) {
      if (!doc.paths.some(item => item.path === savedPath)) doc.paths.push(location);
    } else { doc = { id: `new-${++nextId}`, version: 1, body: input.body, paths: [location] }; docs.push(doc); }
    const receipt = { document_id: doc.id, version: doc.version, relative_path: savedPath, space_id: "lib" };
    ledger.set(input.operation_id, { input, receipt });
    if (postGate) await postGate;
    if (outcome === "network") return route.abort("internetdisconnected");
    if (outcome === "500") return reply({ detail: "服务端连接中断" }, 500);
    if (outcome === "missing") return reply({ document_id: doc.id });
    return reply(receipt);
  }
  if (pathname.includes("/knowledge/sources/")) {
    if (sourceGate) await sourceGate;
    if (failSource) return reply({ detail: "原文暂时离线" }, 503);
    const doc = docs.find(item => item.id === decodeURIComponent(pathname.split("/").at(-1)));
    assert.ok(doc); return reply(source(doc));
  }
  return reply([]);
});
const editor = page.getByRole("region", { name: "笔记编辑与预览" });
const title = page.getByRole("textbox", { name: "笔记标题", exact: true });
const body = page.getByRole("textbox", { name: "Markdown 正文", exact: true });
const tags = page.getByRole("textbox", { name: /^标签/ });
const location = page.getByRole("textbox", { name: /^文件位置/ });
const save = () => page.getByRole("button", { name: /^(保存新版本|保存新笔记|确认上次保存)$/ });
const dirty = () => page.getByText("未保存", { exact: true });
const tick = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const idle = async () => { await page.waitForFunction(() => !document.querySelector('.mt-knowledge-page > [role="status"]')?.textContent.includes("正在处理")); await tick(); };
const fill = async values => { for (const [field, value] of Object.entries(values)) await ({ title, body, tags, location })[field].fill(value); };
const assertFields = async values => { for (const [field, value] of Object.entries(values)) assert.equal(await ({ title, body, tags, location })[field].inputValue(), value); };
const waitWrites = async count => { for (let i = 0; writes.length < count && i < 100; i++) await page.waitForTimeout(20); assert.equal(writes.length, count); };
const gate = kind => { let release; const promise = new Promise(resolve => { release = resolve; }); if (kind === "post") postGate = promise; else sourceGate = promise; return () => { if (kind === "post") postGate = undefined; else sourceGate = undefined; release(); }; };
const noteButton = name => page.getByRole("list", { name: "资料文件列表" }).getByRole("button", { name: new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).first();
const pass = text => { checks.push(text); console.log(`PASS ${text}`); };
try {
  await page.goto(`${base}/math-tutor/knowledge?library=lib`);
  await noteButton("old.md").click(); await body.waitFor(); await idle();
  const a = { title: "标题 A", body: "提交 A\n完整推导", tags: "函数, A", location: "A/提交.md" };
  const b = { title: "标题 B", body: "后续 B\n不能误清", tags: "导数, B", location: "B/新位置.md" };
  await fill(a); const releasePost = gate("post"); await save().click(); await waitWrites(1);
  await fill(b); assert.equal(await title.isEditable(), true); assert.equal(await body.isEditable(), true);
  const releaseRead = gate("source"); releasePost(); await tick();
  await body.fill("后续 C\n读取期间继续编辑"); releaseRead(); await idle();
  b.body = "后续 C\n读取期间继续编辑";
  await assertFields(b); assert.equal(await dirty().count(), 1);
  await page.getByRole("status").filter({ hasText: /上次提交已保存为 v2，仍有未保存修改/ }).waitFor();
  await page.locator('[aria-label="笔记编辑与预览"]').screenshot({ path: path.join(output, "newer-edit-still-unsaved.png") });
  const url = page.url(); await page.getByRole("link", { name: "题库", exact: true }).click();
  assert.equal(page.url(), url); assert.equal(leaveConfirmations, 1); await assertFields(b);
  assert.equal(await page.evaluate(() => { const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; }), true);
  await save().click(); await idle(); assert.equal(writes[1].expected_version, 2); assert.equal(writes[1].previous_relative_path, a.location);
  assert.notEqual(writes[1].operation_id, writes[0].operation_id); assert.equal(writes[1].body, b.body); assert.equal(await dirty().count(), 0);
  pass("existing note: delayed POST and read preserve all newer fields, dirty badge/navigation/unload guard; next save advances CAS/path with a new operation");

  await fill({ title: "已保存 D", body: "保存成功，读取失败", tags: "D", location: "D.md" });
  failSource = failList = true; await save().click(); await page.getByRole("alert").filter({ hasText: "笔记已保存" }).waitFor(); await idle();
  const beforeRefresh = writes.length; assert.equal(await dirty().count(), 0); assert.equal(await save().isDisabled(), true);
  await body.fill("读取失败之后新增 E"); failSource = failList = false;
  await page.getByRole("button", { name: "刷新重试", exact: true }).click(); await idle();
  assert.equal(writes.length, beforeRefresh); assert.equal(await body.inputValue(), "读取失败之后新增 E"); assert.equal(await dirty().count(), 1);
  await save().click(); await idle(); assert.equal(writes.at(-1).expected_version, 4); assert.equal(writes.at(-1).previous_relative_path, "D.md");
  pass("successful write plus failed source/list reads keeps the confirmed version; refresh only reads and cannot discard later edits");

  await page.getByRole("button", { name: "新建笔记", exact: true }).click();
  await fill({ title: "新笔记 A", body: "新建原稿 A", tags: "新建 A", location: "新建/A.md" });
  const newBefore = nextId, writesBeforeNew = writes.length, releaseNew = gate("post");
  await save().click(); await waitWrites(writesBeforeNew + 1);
  const newerNew = { title: "新笔记 B", body: "新建后续 B", tags: "新建 B", location: "新建/B.md" };
  await fill(newerNew); failSource = failList = true; releaseNew();
  await page.getByRole("alert").filter({ hasText: "笔记已保存" }).waitFor(); await idle(); await assertFields(newerNew);
  failSource = failList = false; await save().click(); await idle();
  assert.equal(nextId, newBefore + 1); assert.equal(writes.at(-1).document_id, `new-${nextId}`); assert.equal(writes.at(-1).expected_version, 1); assert.equal(writes.at(-1).previous_relative_path, "新建/A.md");
  pass("new note keeps its acknowledged identity through read failure and later edits; retry updates one document instead of creating another");

  for (const outcome of ["network", "500", "missing"]) {
    await page.getByRole("button", { name: "新建笔记", exact: true }).click();
    await fill({ title: `未知 ${outcome}`, body: `最初提交 ${outcome}`, tags: "最初", location: `${outcome}/A.md` });
    nextOutcome = outcome; const before = writes.length, count = nextId;
    await save().click(); await page.getByRole("alert").filter({ hasText: "保存结果尚未确认" }).waitFor(); await idle();
    const newer = { title: `继续 ${outcome}`, body: `后续内容 ${outcome}`, tags: "后续", location: `${outcome}/B.md` };
    await fill(newer); await page.getByRole("button", { name: "确认上次保存", exact: true }).click(); await idle();
    assert.deepEqual(writes[before + 1], writes[before]); await assertFields(newer); assert.equal(await dirty().count(), 1);
    await save().click(); await idle(); assert.equal(nextId, count + 1); assert.equal(writes.at(-1).document_id, `new-${nextId}`); assert.equal(writes.at(-1).body, newer.body);
    assert.notEqual(writes.at(-1).operation_id, writes[before].operation_id);
  }
  pass("network loss, HTTP 500 and missing-version receipts replay the original immutable request, preserve newer edits, then save them without duplicate notes");

  await body.fill("明确拒绝的内容"); nextOutcome = "reject"; const rejectedAt = writes.length;
  await save().click(); await page.getByRole("alert").filter({ hasText: "版本冲突" }).waitFor(); await idle();
  await body.fill("修正后的内容"); await save().click(); await idle();
  assert.notEqual(writes[rejectedAt].operation_id, writes[rejectedAt + 1].operation_id);
  assert.equal(writes.at(-1).body, "修正后的内容");
  pass("explicit write rejection preserves dirty input and permits a corrected snapshot with a new operation");

  await body.fill("本次确认的提交"); const externalAt = writes.length, releaseExternal = gate("post");
  await save().click(); await waitWrites(externalAt + 1); await body.fill("外部更新时保留的本地推导");
  const external = docs.find(item => item.id === writes[externalAt].document_id), confirmedVersion = external.version;
  external.version++; external.body = "另一客户端提交的新内容";
  releaseExternal(); await page.getByRole("alert").filter({ hasText: "服务端随后又有新版本" }).waitFor(); await idle();
  await save().click(); await page.getByRole("alert").filter({ hasText: "版本冲突" }).waitFor(); await idle();
  assert.equal(writes.at(-1).expected_version, confirmedVersion); assert.equal(await body.inputValue(), "外部更新时保留的本地推导");
  allowLeave = true; await page.getByRole("button", { name: "新建笔记", exact: true }).click(); allowLeave = false;
  await fill({ title: "切换测试", body: "准备切换测试", tags: "", location: "切换.md" }); await save().click(); await idle();
  pass("a newer server read never advances the acknowledged CAS baseline; conflicting local edits remain protected");

  await body.fill("切换前提交"); const staleAt = writes.length, releaseStale = gate("post"); await save().click(); await waitWrites(staleAt + 1);
  await page.evaluate(() => history.pushState({}, "", "/math-tutor/knowledge?library=lib&source=other"));
  await page.waitForFunction(() => document.querySelector('[aria-label="笔记编辑与预览"] textarea')?.value === "另一份文档正文");
  await body.fill("另一份文档的新输入"); releaseStale(); await idle();
  assert.equal(await body.inputValue(), "另一份文档的新输入"); assert.equal(await title.inputValue(), "other.md"); assert.equal(await dirty().count(), 1);
  await save().click(); await idle(); assert.equal(writes.at(-1).document_id, "other"); assert.equal(writes.at(-1).expected_version, 1);
  pass("late completion after a source URL change cannot replace or clear another document's editor");

  const folder = path.join(output, "导入文件夹"); await mkdir(path.join(folder, "一章"), { recursive: true }); await mkdir(path.join(folder, "二章"), { recursive: true });
  await writeFile(path.join(folder, "一章", "甲.md"), "两份路径共用同一份正文"); await writeFile(path.join(folder, "二章", "乙.md"), "两份路径共用同一份正文");
  const importFolder = async () => { const pending = page.waitForEvent("filechooser"); await page.getByRole("button", { name: "导入笔记文件夹", exact: true }).click(); await (await pending).setFiles(folder); await idle(); };
  const beforeFolder = writes.length; await importFolder();
  await page.getByRole("status").filter({ hasText: "已导入 2 个文件，包含 1 份不同正文，保留 2 个位置" }).waitFor();
  assert.equal(writes.length, beforeFolder + 2); assert.equal(ledger.get(writes.at(-1).operation_id).receipt.document_id, ledger.get(writes.at(-2).operation_id).receipt.document_id);
  await importFolder(); assert.equal(writes.length, beforeFolder + 2);
  await page.getByRole("textbox", { name: "按标题、文件夹或标签筛选", exact: true }).fill("甲.md"); await noteButton("甲.md").click(); await idle();
  await tags.fill("甲的标签"); await save().click(); await idle();
  await page.getByRole("textbox", { name: "按标题、文件夹或标签筛选", exact: true }).fill("乙.md"); await noteButton("乙.md").click(); await idle();
  assert.equal(await title.inputValue(), "乙.md"); assert.equal(await tags.inputValue(), "");
  await tags.fill("乙的标签"); await save().click(); await idle();
  await page.getByRole("textbox", { name: "按标题、文件夹或标签筛选", exact: true }).fill("甲的标签"); await noteButton("甲.md").click(); await idle();
  assert.equal(await title.inputValue(), "甲.md"); assert.equal(await tags.inputValue(), "甲的标签");
  pass("ordinary folder import reports input files/unique bodies/retained positions, preserves both paths on reimport, and opens each location with its own title/tags");

  await page.screenshot({ path: path.join(output, "note-save-and-alias.png"), fullPage: true });
  await page.evaluate(() => history.pushState({}, "", "/math-tutor/knowledge?library=lib&source=old"));
  await page.waitForFunction(expected => document.querySelector('input[maxlength="512"]')?.value === expected, docs.find(item => item.id === "old").paths[0].path);
  await page.evaluate(() => history.pushState({}, "", "/math-tutor/knowledge?library=lib-other&source=old"));
  await page.getByRole("heading", { name: "另一知识库", exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector('input[maxlength="512"]')?.value === "另一库/共享.md");
  await assertFields({ title: "另一库标题.md", tags: "另一库标签", location: "另一库/共享.md" });
  pass("switching libraries for the same shared document waits for destination aliases and never reuses the previous library's title, tags or path");
  await editor.screenshot({ path: path.join(output, "destination-library-alias.png") });
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "results.json"), JSON.stringify({ checks, errors, writes, documents: docs }, null, 2));
  console.log(`Evidence: ${output}`);
} catch (error) { await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }); console.error(`Failure evidence: ${output}`); throw error; }
finally { await browser.close(); }

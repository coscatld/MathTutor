// Browser interaction/visual checks. Every API and WebSocket is isolated by
// fixtures; no installed application data or model endpoint is accessed.
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.LAYOUT_URL || "http://localhost:3197";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-learning-support-"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.emulateMedia({ reducedMotion: "reduce" });
const errors = [], mutations = [], previews = [], layouts = [];
let failNextWrite = false, failReadAfterWrite = false, failNextRead = "";
const failedReads = new Set();
page.on("pageerror", error => errors.push(error.message));
const settings = { is_configured: true, onboarding_completed: true, preset_id: "local", model: "fixture", base_url: "http://127.0.0.1", key_masked: null, provider_configs: {} };
const goal = "先确定对数函数的定义域，再讨论单调性";
const session = {
  cycle_id: "fixture-cycle", state_version: 1, state: "awaiting_attempt",
  assistance_level: 2, allowed_next_inputs: ["submit_attempt", "request_hint", "request_explanation"],
  teaching_plan: { action: "ASK_STEP", strategy: "guided_steps", question_goal: goal, reason_codes: ["current_subgoal"], target_skill_ids: [], exit_options: [], support_mode: "step" },
  problem_context: { problem_id: "fixture-problem", display_text: "讨论函数 f(x)=ln(x-1) 的定义域与单调性", lifecycle: "ACTIVE", skill_ids: [], current_subgoal: { id: "domain", status: "pending", prompt_target: goal } },
  evidence_summary: { independent: 1, assisted: 2, post_solution: 0, diagnostic: 0, ungradable: 0, status: "needs_confirmation" },
  messages: [{ message_id: "fixture-student", role: "student", content: "我不明白为什么先看定义域。" }, { message_id: "fixture-tutor", role: "tutor", content: "对数的真数必须为正。先想一想 x−1>0 对 x 有什么要求。", action: "ASK_STEP", assistance_level: 2 }],
};
const documents = [
  { document_id: "d-ready", filename: "函数与导数 · 课堂讲义.pdf", status: "ready", retrieval_enabled: true, chunk_count: 12 },
  { document_id: "d-off", filename: "旧版复习笔记.md", status: "ready", retrieval_enabled: false, chunk_count: 5 },
  { document_id: "d-failed", filename: "待重新扫描的讲义.pdf", status: "needs_ocr", retrieval_enabled: true, chunk_count: 0, error: "未检测到可检索文字" },
].map(row => ({ ...row, created_at: "2026-10-16T09:00:00Z", is_global: false, conversation_ids: ["support"] }));
let memories = Array.from({ length: 23 }, (_, i) => ({
  memory_id: `memory-${i}`, memory_type: "example_preference", subject: `讲解偏好 ${i + 1}`, predicate: "内容", object_json: { value: i === 22 ? "最新偏好：先给一个具体例子，再解释抽象定义。" : `学习偏好 ${i + 1}：请保留必要的中间步骤。` },
  source_type: i === 21 ? "MODEL_INFERRED" : "USER_EXPLICIT", confidence: .9, retrieval_enabled: i !== 20, created_at: "2026-10-16T09:00:00Z", updated_at: "2026-10-16T09:00:00Z",
}));
const libraries = [{ space_id: "lib-functions", name: "高中函数笔记", kind: "course", conversation_id: "", enabled: 1 }, { space_id: "lib-personal", name: "我的错题整理", kind: "personal", conversation_id: "", enabled: 1 }, { space_id: "lib-other-session", name: "其他对话的专属资料", kind: "session", conversation_id: "other", enabled: 1 }];
const notes = [{ document_id: "note-domain", title: "对数函数的定义域.md", version: 2, tags: ["函数", "定义域"], links: [], retrieval_enabled: true, editable: true }];
const initialMount = { space_ids: ["lib-functions"], document_ids: [], only_selected: false, mode: "tutor", hints_only: false, save_space_id: "lib-functions", tool_mode: "structured" };
const mounts = new Map([["support", initialMount]]);
const config = cid => mounts.get(cid) || { space_ids: [], document_ids: [], only_selected: false, mode: "tutor", hints_only: false, save_space_id: "", tool_mode: "native" };
const scopeProjection = (cid, value = config(cid)) => {
  const candidates = [
    ...(cid === "support" ? documents.map(doc => ({document_id: doc.document_id, title: doc.filename, enabled: doc.retrieval_enabled && ["ready", "ready_with_warnings"].includes(doc.status), status: doc.status, retrieval_enabled: doc.retrieval_enabled, origin: "conversation", space_ids: []})) : []),
    ...(value.space_ids.includes("lib-functions") ? [{document_id: "note-domain", title: notes[0].title, enabled: true, status: "ready", retrieval_enabled: true, origin: "library", space_ids: ["lib-functions"]}] : []),
    ...(value.space_ids.includes("lib-personal") ? [{document_id: "note-mistake", title: "本周易错题.md", enabled: true, status: "ready", retrieval_enabled: true, origin: "library", space_ids: ["lib-personal"]}] : []),
  ].map(doc => ({...doc, selected: !value.only_selected || value.document_ids.includes(doc.document_id)}));
  return {...value, available_documents: candidates, effective_document_ids: candidates.filter(doc => doc.selected && doc.enabled).map(doc => doc.document_id)};
};
await page.route("**/api/**", async route => {
  const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method();
  let body = [];
  if (pathname.endsWith("/auth/status")) body = { enabled: false, authenticated: true };
  else if (pathname.endsWith("/bootstrap")) body = { phase: "READY", readiness: "READY", steps: [] };
  else if (pathname.endsWith("/settings")) body = settings;
  else if (pathname.endsWith("/presets")) body = [];
  else if (pathname.endsWith("/sessions")) body = [{ conversation_id: "support", title: "函数与定义域" }];
  else if (pathname.includes("/sessions/")) body = session;
  else if (pathname.endsWith("/resources")) {
    const cid = decodeURIComponent(pathname.split("/").at(-2)), scope = scopeProjection(cid);
    const projected = scope.available_documents.map(candidate => ({...(documents.find(doc => doc.document_id === candidate.document_id) || {document_id: candidate.document_id, filename: candidate.title, status: "ready", retrieval_enabled: true, chunk_count: 3, created_at: "2026-10-16T09:00:00Z"}), in_scope: scope.effective_document_ids.includes(candidate.document_id), origin: candidate.origin, space_ids: candidate.space_ids}));
    body = {documents: projected, images: [], message_count: 2, scope};
  }
  else if (pathname.endsWith("/memory")) body = memories;
  else if (/\/memory\/[^/]+\/retrieval$/.test(pathname)) {
    const id = pathname.split("/").at(-2), input = request.postDataJSON();
    memories = memories.map(row => row.memory_id === id ? { ...row, retrieval_enabled: input.enabled } : row);
    body = memories.find(row => row.memory_id === id); mutations.push({ kind: "memory-retrieval", id, ...input });
  } else if (/\/memory\/[^/]+\/confirm$/.test(pathname)) {
    const id = pathname.split("/").at(-2);
    memories = memories.map(row => row.memory_id === id ? { ...row, source_type: "USER_CONFIRMED" } : row);
    body = memories.find(row => row.memory_id === id); mutations.push({ kind: "memory-confirm", id });
  } else if (pathname.endsWith("/knowledge/libraries")) body = libraries;
  else if (pathname.endsWith("/knowledge/drafts")) body = [];
  else if (/\/knowledge\/libraries\/[^/]+\/notes$/.test(pathname)) body = notes;
  else if (/\/knowledge\/conversations\/[^/]+\/preview$/.test(pathname)) {
    const cid = decodeURIComponent(pathname.split("/").at(-2)), input = request.postDataJSON();
    assert.equal(method, "POST"); previews.push({cid, ...input}); body = scopeProjection(cid, input);
  } else if (/\/knowledge\/conversations\/[^/]+$/.test(pathname)) {
    const cid = decodeURIComponent(pathname.split("/").at(-1));
    if (method === "GET" && (failNextRead === cid || failedReads.has(cid))) { failNextRead = ""; return route.fulfill({status: 503, json: {detail: "模拟范围读取失败"}}); }
    if (method === "PUT") {
      if (failNextWrite) { failNextWrite = false; return route.fulfill({status: 409, json: {detail: "模拟保存冲突，原范围仍有效"}}); }
      const input = request.postDataJSON();
      assert.equal("available_documents" in input, false); assert.equal("effective_document_ids" in input, false);
      mounts.set(cid, input); mutations.push({kind: "mount", cid, ...input});
      if (failReadAfterWrite) { failReadAfterWrite = false; failNextRead = cid; }
    }
    body = scopeProjection(cid);
  } else if (pathname.endsWith("/knowledge/sources/note-domain")) body = { ...notes[0], body: "# 对数函数\n\n真数必须大于零。", body_hash: "fixture-hash", provenance: { format: "markdown" }, backlinks: [] };
  else if (pathname.endsWith("/documents")) body = documents;
  else if (pathname.includes("embedding")) body = { enabled: false, status: "disabled", local_models: [] };
  await route.fulfill({ json: body });
});
await page.routeWebSocket("**/api/**", () => {});

const checkBounds = async () => {
  await page.waitForFunction(() => document.querySelector(".mt-sidebar")?.getAttribute("data-collapsed") === (innerWidth <= 800 ? "true" : "false"));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "page must not scroll horizontally");
  const panel = await page.locator(".mt-tools-panel").count() ? await page.locator(".mt-tools-panel").boundingBox() : null;
  if (panel) assert.ok(panel.x >= 0 && panel.y >= 0 && panel.x + panel.width <= page.viewportSize().width + 1 && panel.y + panel.height <= page.viewportSize().height + 1, "tool panel must remain inside viewport");
};
const capture = async name => {
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  layouts.push({ name, ...await page.evaluate(() => ({ viewport: [innerWidth, innerHeight], document: [document.documentElement.scrollWidth, document.documentElement.scrollHeight], content: [document.querySelector("#workspace-content")?.clientHeight, document.querySelector("#workspace-content")?.scrollHeight] })) });
  await page.screenshot({ path: path.join(output, `${name}.png`), animations: "disabled" }); console.log(`checked ${name}`);
};
try {
  await page.goto(`${base}/math-tutor?session=support`);
  await page.getByRole("button", { name: "当前教学支持与可用操作", exact: true }).click();
  await page.locator(".mt-tools-panel").getByText(goal, { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "收起右侧工具", exact: true }).count(), 0);
  await checkBounds(); await capture("teaching-desktop");
  await page.keyboard.press("Escape");
  assert.equal(await page.getByRole("button", { name: "当前教学支持与可用操作", exact: true }).evaluate(el => el === document.activeElement), true);
  await page.getByRole("button", { name: "当前对话的学习资料", exact: true }).click();
  await page.locator(".mt-tools-panel").getByText(documents[0].filename, { exact: true }).first().waitFor();
  await page.locator(".mt-tools-panel").getByText(documents[2].filename, { exact: true }).first().waitFor();
  await checkBounds(); await capture("documents-desktop");
  const reference = page.getByRole("region", {name: "回答参考资料", exact: true});
  const applyScope = reference.getByRole("button", {name: "应用到当前对话", exact: true});
  assert.equal(await page.getByRole("link", {name: "知识库与问答范围", exact: true}).count(), 0);
  assert.equal(await reference.getByRole("checkbox", {name: "其他对话的专属资料", exact: true}).count(), 0);
  await reference.getByRole("checkbox", {name: libraries[1].name, exact: true}).check();
  await reference.getByText("本周易错题.md", {exact: true}).waitFor();
  assert.equal(mutations.filter(row => row.kind === "mount").length, 0, "preview cannot persist a configuration");
  await page.keyboard.press("Escape");
  await page.getByRole("button", {name: "当前对话的学习资料", exact: true}).click();
  assert.equal(await reference.getByRole("checkbox", {name: libraries[1].name, exact: true}).isChecked(), true, "closing the panel preserves its draft");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", {name: "新建对话", exact: true}).click();
  assert.ok(page.url().includes("session=support"), "canceling new-conversation navigation retains the current draft");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("link", {name: "打开知识库", exact: true}).click();
  assert.ok(page.url().includes("session=support"), "canceling link navigation retains the current draft");
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("link", {name: "打开知识库", exact: true}).click();
  await page.waitForURL("**/math-tutor/knowledge?conversation=support");
  await page.goBack();
  await page.waitForURL("**/math-tutor?session=support");
  await page.getByRole("button", {name: "当前对话的学习资料", exact: true}).click();
  await reference.getByText("本周易错题.md", {exact: true}).waitFor();
  assert.equal(await reference.getByRole("checkbox", {name: libraries[1].name, exact: true}).isChecked(), true, "Back restores only this conversation's draft");
  await applyScope.click();
  await reference.getByText("已应用，下一条消息将使用这个资料范围。", {exact: true}).waitFor();
  assert.deepEqual(config("support").space_ids, ["lib-functions", "lib-personal"]);
  assert.equal(config("support").tool_mode, "structured");
  assert.equal(config("support").save_space_id, "lib-functions");
  await reference.getByRole("checkbox", {name: /仅使用我勾选的文档/}).check();
  await applyScope.click();
  assert.deepEqual(scopeProjection("support").effective_document_ids, [], "a strict empty selection must stay empty");
  await reference.getByRole("checkbox", {name: notes[0].title, exact: true}).check();
  await applyScope.click();
  assert.deepEqual(scopeProjection("support").effective_document_ids, ["note-domain"]);
  await reference.getByRole("checkbox", {name: documents[0].filename, exact: true}).check();
  const savedBeforeFailure = mutations.filter(row => row.kind === "mount").length;
  failNextWrite = true;
  await applyScope.click();
  await reference.getByText("模拟保存冲突，原范围仍有效", {exact: true}).waitFor();
  assert.equal(mutations.filter(row => row.kind === "mount").length, savedBeforeFailure);
  assert.deepEqual(config("support").document_ids, ["note-domain"]);
  await reference.getByRole("button", {name: "重新读取范围", exact: true}).click();
  failReadAfterWrite = true;
  await applyScope.click();
  await reference.getByText("设置已提交，但尚未确认当前范围。请重新读取后再继续对话。", {exact: true}).waitFor();
  assert.equal(await page.getByRole("textbox", {name: "聊天输入", exact: true}).isDisabled(), true);
  await reference.getByRole("button", {name: "重新读取范围", exact: true}).click();
  await reference.getByText("已应用", {exact: true}).waitFor();
  assert.equal(await page.getByText("资料范围尚待确认，请在对话资料中重新读取后继续。", {exact: true}).count(), 0);
  failedReads.add("read-failed");
  const writesBeforeReadFailure = mutations.filter(row => row.kind === "mount").length;
  await page.goto(`${base}/math-tutor?session=read-failed&panel=documents`);
  await reference.getByText("模拟范围读取失败", {exact: true}).waitFor();
  assert.equal(await applyScope.count(), 0, "failed initial reads cannot save an invented default");
  assert.equal(mutations.filter(row => row.kind === "mount").length, writesBeforeReadFailure);
  failedReads.delete("read-failed");
  await reference.getByRole("button", {name: "重新读取范围", exact: true}).click();
  await reference.getByText("已应用", {exact: true}).waitFor();
  assert.equal(await reference.getByRole("checkbox", {name: libraries[1].name, exact: true}).isChecked(), false, "conversation drafts never cross session IDs");
  await page.goto(`${base}/math-tutor?session=support&panel=documents`);
  await reference.getByText("已应用", {exact: true}).waitFor();
  assert.equal(await reference.getByRole("checkbox", {name: documents[0].filename, exact: true}).isChecked(), true);
  assert.ok(previews.length > 1, "scope edits use read-only previews");
  await checkBounds(); await capture("documents-selected-scope");
  await page.getByRole("button", { name: "关闭工具栏", exact: true }).click();
  await page.getByRole("button", { name: "查看 Tutor 使用的学习记忆", exact: true }).click();
  const panel = page.locator(".mt-tools-panel");
  await panel.getByText(memories[22].object_json.value, { exact: true }).waitFor();
  assert.equal(await panel.locator("li").count(), 23, "all saved memories must remain accessible");
  await panel.getByRole("checkbox").first().click();
  await page.waitForFunction(() => document.querySelector('.mt-tools-panel input[type="checkbox"]')?.checked === false);
  assert.ok(mutations.some(row => row.kind === "memory-retrieval" && row.enabled === false));
  await panel.getByRole("button", { name: "确认这条记忆", exact: true }).click();
  await panel.getByRole("button", { name: "确认这条记忆", exact: true }).waitFor({ state: "hidden" });
  assert.ok(mutations.some(row => row.kind === "memory-confirm"));
  await panel.evaluate(el => el.querySelector('.mt-tools-body')?.scrollTo(0, 0));
  await capture("memory-desktop");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 375, height: 812 });
  await page.locator("#workspace-content").evaluate(el => el.scrollTo(0, 0));
  await page.getByRole("button", { name: "当前对话的学习资料", exact: true }).click();
  await panel.getByText(documents[0].filename, { exact: true }).waitFor();
  await checkBounds(); await capture("documents-mobile");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 812, height: 375 });
  await page.getByRole("button", { name: "当前教学支持与可用操作", exact: true }).click();
  await checkBounds(); await capture("teaching-landscape");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/math-tutor/knowledge?conversation=support`);
  assert.equal(await page.getByRole("link", {name: /返回对话/}).count(), 0, "knowledge has no explicit return-to-chat link");
  assert.equal(await page.getByRole("button", {name: /返回对话|能力扩展/}).count(), 0, "developer extensions and return buttons are absent");
  await page.getByText(libraries[0].name, { exact: true }).first().waitFor();
  assert.equal(await page.getByRole("region", {name: "会话挂载", exact: true}).count(), 0, "knowledge management has no duplicate scope editor");
  await page.locator(".mt-library-choice").filter({ hasText: libraries[0].name }).click();
  await page.locator(".mt-note-open").filter({ hasText: notes[0].title }).click();
  await page.getByRole("textbox", { name: "笔记标题", exact: true }).waitFor();
  await page.waitForFunction(title => Array.from(document.querySelectorAll("input")).some(input => input.value === title), notes[0].title);
  assert.equal(await page.getByRole("textbox", { name: "笔记标题", exact: true }).inputValue(), notes[0].title);
  await page.locator("#workspace-content").evaluate(el => el.scrollTo(0, 0));
  await checkBounds(); await capture("knowledge-desktop");
  await page.setViewportSize({ width: 375, height: 812 });
  await checkBounds(); await capture("knowledge-mobile");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await checkBounds(); await capture("knowledge-dark-mobile");
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({ status: "PASS", mocked_traffic: true, paid_model_calls: 0, mutations, previews, layouts, page_errors: errors }, null, 2));
  console.log(JSON.stringify({ status: "PASS", output, paid_model_calls: 0 }));
} finally { await browser.close(); }

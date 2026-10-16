// Ordinary knowledge UI acceptance. Developer workspace/tool APIs remain covered
// by backend tests; this browser must never request or expose those controls.
// All traffic is synthetic, with no model or real filesystem access.
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.LAYOUT_URL || "http://localhost:3198";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-knowledge-skills-"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const errors = [], requests = [], screenshots = [], forbidden = [];
let failNextCatalog = false;
page.on("pageerror", error => errors.push(error.message));
await page.emulateMedia({ reducedMotion: "reduce" });
const library = {space_id: "fixture-library", name: "我的数学笔记", kind: "course", conversation_id: "", enabled: 1};
const catalog = {api_version: "developer-only-marker", sdk: {registration: "DO_NOT_DISPLAY_SDK"},
  skills: [{id: "fixture.canvas", name: "交互画布作图", description: "结合函数与几何图形理解数学。", enabled: true, source: "builtin", activation: "数学对话按需提供"}, {id: "fixture.stepwise", name: "逐步讲解", description: "围绕学生当前疑点提供明确的小步骤。", enabled: false, source: "configured"}],
  tools: [{name: "DO_NOT_DISPLAY_TOOL", input_schema: {secret: "DO_NOT_DISPLAY_SCHEMA"}}],
  workspaces: [{workspace_id: "DO_NOT_DISPLAY_WORKSPACE", name: "DO_NOT_DISPLAY_DIRECTORY"}]};
await page.route("**/api/**", async route => {
  const request = route.request(), pathname = new URL(request.url()).pathname, method = request.method();
  requests.push({pathname, method}); let body = [];
  if (pathname.endsWith("/auth/status")) body = {enabled: false, authenticated: true};
  else if (pathname.endsWith("/bootstrap")) body = {phase: "READY", readiness: "READY", steps: []};
  else if (pathname.endsWith("/settings")) body = {is_configured: true, onboarding_completed: true, preset_id: "local", model: "fixture", base_url: "http://127.0.0.1", key_masked: null, provider_configs: {}};
  else if (pathname.endsWith("/creator/catalog") && method === "GET") {
    if (failNextCatalog) {failNextCatalog = false; return route.fulfill({status: 503, json: {detail: "fixture failure"}});}
    body = catalog;
  } else if (pathname.includes("/creator/")) {forbidden.push({pathname, method}); return route.fulfill({status: 403, json: {detail: "Developer APIs are unavailable in this ordinary UI fixture."}});}
  else if (pathname.endsWith("/knowledge/libraries")) body = [library];
  else if (pathname.endsWith("/knowledge/drafts")) body = [];
  else if (/\/knowledge\/libraries\/[^/]+\/notes$/.test(pathname)) body = [];
  await route.fulfill({json: body});
});
await page.routeWebSocket("**/api/**", () => {});
const tabs = page.getByRole("navigation", {name: "知识库内容类型"});
const assertOrdinaryUi = async () => {
  assert.equal(await tabs.getByRole("button").count(), 2);
  assert.equal(await page.getByRole("button", {name: /能力扩展|添加.*授权|选择文件夹|返回对话/}).count(), 0);
  assert.equal(await page.getByRole("link", {name: /返回对话/}).count(), 0);
  assert.equal(await page.getByRole("region", {name: /智能体能力扩展|已注册工具|文件读写文件夹/}).count(), 0);
  assert.doesNotMatch(await page.locator(".mt-knowledge-page").innerText(), /SDK|创作者接口|input_schema|DO_NOT_DISPLAY|目录授权|为 MathTutor 创建新能力/);
  assert.equal(await page.getByRole("navigation", {name: "主要功能"}).getByRole("link", {name: "辅导", exact: true}).count(), 1, "ordinary sidebar navigation stays available");
};
const capture = async name => {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "knowledge UI cannot overflow horizontally");
  await page.screenshot({path: path.join(output, `${name}.png`), animations: "disabled"});
  screenshots.push({name, viewport: page.viewportSize()});
};
try {
  await page.goto(`${base}/math-tutor/knowledge?conversation=knowledge-fixture&tab=extensions`);
  await page.getByRole("heading", {name: "知识库", exact: true}).waitFor();
  await page.getByText(library.name, {exact: true}).waitFor();
  assert.equal(await tabs.getByRole("button", {name: "题库与笔记", exact: true}).getAttribute("aria-pressed"), "true", "old extension links fall back to files");
  assert.equal(requests.filter(row => row.pathname.endsWith("/creator/catalog")).length, 0, "files view does not load the shared skill catalog");
  await assertOrdinaryUi(); await capture("knowledge-files-desktop");
  await tabs.getByRole("button", {name: "教学技能", exact: true}).click();
  await page.getByRole("heading", {name: "交互画布作图", exact: true}).waitFor();
  const skills = page.getByRole("region", {name: "教学技能", exact: true});
  assert.equal(await skills.getByText("未启用", {exact: true}).count(), 1);
  await assertOrdinaryUi(); await capture("teaching-skills-desktop");
  failNextCatalog = true; await tabs.getByRole("button", {name: "题库与笔记", exact: true}).click(); await tabs.getByRole("button", {name: "教学技能", exact: true}).click();
  await skills.getByRole("alert").waitFor(); assert.equal(await skills.getByRole("heading", {name: "交互画布作图", exact: true}).count(), 0, "failed refresh cannot show stale availability");
  await skills.getByRole("button", {name: "重新读取", exact: true}).click(); await skills.getByRole("heading", {name: "交互画布作图", exact: true}).waitFor();
  await page.goto(`${base}/math-tutor/knowledge?tab=skills`); await page.getByRole("heading", {name: "交互画布作图", exact: true}).waitFor();
  assert.equal(await tabs.getByRole("button", {name: "教学技能", exact: true}).getAttribute("aria-pressed"), "true");
  await page.setViewportSize({width: 375, height: 812}); await page.locator("#workspace-content").evaluate(node => node.scrollTo(0, 0)); await assertOrdinaryUi(); await capture("teaching-skills-mobile");
  await page.evaluate(() => document.documentElement.classList.add("dark")); await capture("teaching-skills-dark-mobile");
  assert.deepEqual(forbidden, []); assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({status: "PASS", mocked_traffic: true, paid_model_calls: 0, real_filesystem_writes: 0, requests, forbidden_creator_requests: forbidden, screenshots, page_errors: errors}, null, 2));
  console.log(JSON.stringify({status: "PASS", output, paid_model_calls: 0}));
} finally { await browser.close(); }

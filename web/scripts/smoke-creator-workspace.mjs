// UI-only acceptance with synthetic catalogs and directory grants. No real
// directory, installed user data, native dialog, or model endpoint is accessed.
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.LAYOUT_URL || "http://localhost:3197";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-creator-workspace-"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], mutations = [], screenshots = [];
page.on("pageerror", error => errors.push(error.message));
await page.emulateMedia({ reducedMotion: "reduce" });
let workspaces = [], grantSequence = 0, failNextGrant = false, failNextCatalog = false;
const catalog = () => ({ api_version: "mathtutor.extensions.v1", sdk: { registration: "server-owned", execution: "trusted-in-process", sandbox: false, user_installation: false },
  skills: [{ id: "fixture.stepwise", name: "逐步讲解", description: "按学生当前疑点提供明确的小步骤。", enabled: false, source: "builtin" }],
  tools: [
    { name: "ext_workspace_read_text", title: "读取文本", description: "读取已授权目录中的文本。", active: workspaces.length > 0, source: "builtin", input_schema: { type: "object", additionalProperties: false, properties: { workspace_id: { type: "string" }, relative_path: { type: "string" } } } },
    { name: "ext_workspace_write_text", title: "保存文本", description: "只向用户明确允许写入的目录创建或更新文件。", active: workspaces.some(item => item.writable), source: "builtin", input_schema: { type: "object", additionalProperties: false, properties: { workspace_id: { type: "string" }, relative_path: { type: "string" }, content: { type: "string" } } } },
  ], workspaces });
await page.route("**/api/**", async route => {
  const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method();
  let body = [];
  if (pathname.endsWith("/auth/status")) body = { enabled: false, authenticated: true };
  else if (pathname.endsWith("/bootstrap")) body = { phase: "READY", readiness: "READY", steps: [] };
  else if (pathname.endsWith("/settings")) body = { is_configured: true, onboarding_completed: true, preset_id: "local", model: "fixture", base_url: "http://127.0.0.1", key_masked: null, provider_configs: {} };
  else if (pathname.endsWith("/creator/catalog")) {
    if (failNextCatalog) { failNextCatalog = false; return route.fulfill({status: 503, json: {detail: "模拟权限状态读取失败。"}}); }
    body = catalog();
  }
  else if (pathname.endsWith("/creator/workspaces/pick")) { assert.equal(method, "POST"); mutations.push({ kind: "pick" }); body = { path: "/fixture/我的数学资料", cancelled: false }; }
  else if (pathname.endsWith("/creator/workspaces") && method === "POST") {
    const input = request.postDataJSON();
    assert.deepEqual(Object.keys(input).sort(), ["path", "writable"]);
    if (failNextGrant) { failNextGrant = false; return route.fulfill({ status: 422, json: { detail: "模拟目录授权失败，请检查后重试。" } }); }
    const grant = { workspace_id: `fixture-workspace-${++grantSequence}`, name: input.path.split("/").at(-1), readable: true, writable: input.writable, expires: "process-restart" };
    workspaces.push(grant); mutations.push({ kind: "grant", ...input }); body = grant;
  } else if (/\/creator\/workspaces\/[^/]+$/.test(pathname) && method === "DELETE") {
    const id = decodeURIComponent(pathname.split("/").at(-1));
    workspaces = workspaces.filter(item => item.workspace_id !== id); mutations.push({ kind: "revoke", id }); body = { workspace_id: id, revoked: true };
  }
  await route.fulfill({ json: body });
});
await page.routeWebSocket("**/api/**", () => {});
const capture = async name => {
  await page.evaluate(() => document.fonts.ready);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "creator view cannot overflow horizontally");
  await page.screenshot({ path: path.join(output, `${name}.png`), animations: "disabled" });
  screenshots.push({ name, viewport: page.viewportSize() });
};
try {
  await page.goto(`${base}/math-tutor/knowledge?conversation=creator-fixture`);
  await page.getByRole("button", { name: "教学技能", exact: true }).click();
  await page.getByRole("heading", { name: "逐步讲解", exact: true }).waitFor();
  assert.equal(await page.getByRole("region", { name: "教学技能管理", exact: true }).getByText("未启用", { exact: true }).count(), 1);
  await capture("skills-desktop");
  await page.getByRole("button", { name: "能力扩展", exact: true }).click();
  const access = page.getByRole("region", { name: "文件读写文件夹", exact: true });
  await access.getByText("尚未允许访问任何文件夹。文件工具不会出现在智能体可调用的列表里。", { exact: true }).waitFor();
  const tool = title => page.getByRole("region", { name: "已注册工具", exact: true }).getByRole("article").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
  assert.equal(await tool("读取文本").getByText("未启用", { exact: true }).count(), 1);
  assert.equal(await tool("保存文本").getByText("未启用", { exact: true }).count(), 1);
  await access.getByRole("button", { name: "选择文件夹", exact: true }).click();
  await page.waitForFunction(() => document.querySelector('input[placeholder="选择文件夹，或手动输入完整路径"]')?.value === "/fixture/我的数学资料");
  assert.equal(mutations.filter(item => item.kind === "grant").length, 0, "picking a directory never grants access");
  assert.equal(await access.getByRole("checkbox").isChecked(), false, "directory grants default to read-only");
  await access.getByRole("button", { name: "添加只读授权", exact: true }).click();
  await access.getByText("我的数学资料", { exact: true }).waitFor();
  assert.equal(mutations.find(item => item.kind === "grant").writable, false);
  assert.equal(await tool("读取文本").getByText("可用", { exact: true }).count(), 1);
  assert.equal(await tool("保存文本").getByText("未启用", { exact: true }).count(), 1);
  await access.getByRole("textbox", { name: "文件夹完整路径", exact: true }).fill("/fixture/课堂笔记");
  await access.getByRole("checkbox").check();
  failNextGrant = true;
  await access.getByRole("button", { name: "添加读写授权", exact: true }).click();
  await page.getByRole("alert").getByText("模拟目录授权失败，请检查后重试。", { exact: true }).waitFor();
  assert.equal(await access.getByRole("textbox", { name: "文件夹完整路径", exact: true }).inputValue(), "/fixture/课堂笔记", "failed grants preserve the selected path");
  await access.getByRole("button", { name: "添加读写授权", exact: true }).click();
  await access.getByText("课堂笔记", { exact: true }).waitFor();
  assert.equal(await tool("保存文本").getByText("可用", { exact: true }).count(), 1);
  await capture("extensions-desktop");
  await access.getByRole("button", { name: "撤销课堂笔记的访问权限", exact: true }).click();
  await tool("保存文本").getByText("未启用", { exact: true }).waitFor();
  assert.equal(workspaces.length, 1);
  failNextCatalog = true;
  await access.getByRole("button", { name: "撤销我的数学资料的访问权限", exact: true }).click();
  await page.getByRole("alert").getByText("模拟权限状态读取失败。", {exact: true}).waitFor();
  assert.equal(await access.count(), 0, "failed permission refresh cannot keep showing stale grants");
  assert.equal(await page.getByText("访问权限已撤销，后续工具调用无法继续访问此文件夹。", {exact: true}).count(), 0, "unconfirmed catalog refresh cannot claim confirmed UI state");
  await page.getByRole("alert").getByRole("button", {name: "重新读取", exact: true}).click();
  await access.getByText("尚未允许访问任何文件夹。文件工具不会出现在智能体可调用的列表里。", { exact: true }).waitFor();
  assert.equal(await tool("读取文本").getByText("未启用", { exact: true }).count(), 1);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.locator("#workspace-content").evaluate(node => node.scrollTo(0, 0));
  await capture("extensions-mobile");
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await capture("extensions-dark-mobile");
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({ status: "PASS", mocked_traffic: true, paid_model_calls: 0, real_filesystem_writes: 0, mutations, screenshots, page_errors: errors }, null, 2));
  console.log(JSON.stringify({ status: "PASS", output, paid_model_calls: 0 }));
} finally { await browser.close(); }

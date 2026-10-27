// Full React/dialog/guard/API lifecycle with isolated local API and WebSocket fixtures.
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const base = process.env.LAYOUT_URL || "http://127.0.0.1:3000";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-delete-browser-"));
const checks = [], errors = [];
const pass = name => { checks.push(name); console.log(`PASS ${name}`); };
page.on("pageerror", error => errors.push(error.message));
await page.addInitScript(() => {
  window.__revoked = [];
  const revoke = URL.revokeObjectURL;
  URL.revokeObjectURL = value => { window.__revoked.push(value); revoke(value); };
  const NativeSocket = window.WebSocket;
  class Socket {
    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
    readyState = 0;
    constructor(url, protocols) {
      if (!String(url).includes("/api/v2/math-tutor/ws")) return new NativeSocket(url, protocols);
      window.setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 20);
    }
    send() {}
    close() { this.readyState = 3; this.onclose?.({}); }
  }
  window.WebSocket = Socket;
});
const settings = { is_configured: true, onboarding_completed: true, provider_configs: {} };
const session = { cycle_id: "cycle-a", problem_revision: "revision-1", state_version: 1, state: "awaiting_attempt", allowed_next_inputs: ["send_message", "submit_attempt"], messages: [{ role: "tutor", content: "请独立完成这一步。" }], problem_context: { problem_id: "problem-a", display_text: "解方程 2x=4", lifecycle: "ACTIVE", skill_ids: [] } };
const mount = { space_ids: [], document_ids: [], only_selected: false, mode: "tutor", save_space_id: "", tool_mode: "native", available_documents: [], effective_document_ids: [] };
let conversations = ["a", "b", "c"].map(id => ({ conversation_id: id, title: `对话 ${id.toUpperCase()}` }));
let deletion = "500", requests = 0, deletionGate;
await page.route("**/api/**", async route => {
  const request = route.request(), p = new URL(request.url()).pathname, method = request.method();
  const reply = (json, status = 200) => route.fulfill({ status, json });
  if (p.endsWith("/auth/status")) return reply({ enabled: false, authenticated: true });
  if (p.endsWith("/bootstrap")) return reply({ phase: "READY", readiness: "READY", steps: [] });
  if (p.endsWith("/settings/embedding")) return reply({ status: "disabled", status_label: "关键词检索" });
  if (p.endsWith("/settings")) return reply(settings);
  if (p.endsWith("/sessions")) return reply(conversations);
  if (p.includes("/sessions/")) {
    if (method !== "DELETE") return reply(session);
    requests++;
    const outcome = deletion;
    if (deletionGate) await deletionGate;
    if (outcome === "offline") return route.abort("internetdisconnected");
    if (outcome === "500") return reply({ detail: "删除失败，请重试。" }, 500);
    conversations = conversations.filter(row => row.conversation_id !== p.split("/").at(-1));
    return reply({});
  }
  if (p.endsWith("/knowledge/libraries")) return reply([1, 2].map(id => ({ space_id: `lib-${id}`, name: `参考库 ${id}`, kind: "course", enabled: 1 })));
  if (p.includes("/knowledge/conversations/")) return reply(method === "POST" ? { ...mount, ...request.postDataJSON() } : mount);
  if (p.endsWith("/resources")) return reply({ documents: [], images: [], message_count: 1, scope: mount });
  return reply([]);
});
const input = page.getByRole("textbox", { name: "聊天输入" });
const modal = page.getByRole("dialog", { name: "将此对话移入垃圾桶？" });
const confirm = modal.getByRole("button", { name: "移入垃圾桶", exact: true });
const tick = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const waitInput = async () => { await input.waitFor(); await page.waitForFunction(() => !document.querySelector('[aria-label="聊天输入"]')?.disabled); };
const attach = async () => page.locator('input[type="file"][accept="image/png,image/jpeg,image/webp"]').setInputFiles({ name: "step.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==", "base64") });
const openDelete = async id => { await page.getByRole("button", { name: `删除对话：对话 ${id}`, exact: true }).click(); await modal.waitFor(); };
let confirmations = 0, accept = false, confirmationMessage = "";
page.on("dialog", dialog => { confirmations++; confirmationMessage = dialog.message(); void (accept ? dialog.accept() : dialog.dismiss()); });
const sameDraft = async (text, revoked = 0) => {
  assert.equal(await input.inputValue(), text);
  assert.equal(await page.getByRole("button", { name: /删除图片/ }).count(), 1);
  assert.equal(await page.evaluate(() => window.__revoked.length), revoked);
};
const gateDeletion = () => {
  let release;
  deletionGate = new Promise(resolve => { release = resolve; });
  return () => { deletionGate = undefined; release(); };
};
const waitRequests = async count => {
  for (let attempt = 0; requests < count && attempt < 100; attempt++) await page.waitForTimeout(20);
  assert.equal(requests, count);
};
try {
  await page.goto(`${base}/math-tutor?session=a`); await waitInput();
  const text = "第一步：2x=4\n第二步：x=2";
  await input.fill(text); await attach();
  await input.evaluate(el => { el.setSelectionRange(4, 4); el.focus(); });
  await openDelete("A");
  await confirm.evaluate(el => { el.click(); el.click(); }); await tick();
  assert.equal(confirmations, 1); assert.equal(requests, 0);
  assert.equal(await confirm.isEnabled(), true); assert.equal(await modal.getByRole("button", { name: "取消", exact: true }).isEnabled(), true);
  await sameDraft(text); assert.equal(await input.evaluate(el => el.selectionStart), 4);
  await page.keyboard.press("Escape"); await modal.waitFor({ state: "hidden" }); await tick();
  assert.equal(await page.getByRole("button", { name: "删除对话：对话 A", exact: true }).evaluate(el => el === document.activeElement), true);
  await openDelete("A"); await confirm.click(); await tick();
  await modal.getByRole("button", { name: "取消", exact: true }).click(); await modal.waitFor({ state: "hidden" });
  assert.equal(requests, 0); await sameDraft(text);
  pass("cancelled leave makes zero DELETE requests, preserves multiline/image/cursor, unlocks both buttons, Escape/Cancel restore opener focus");

  accept = true;
  for (const failure of ["500", "offline"]) {
    deletion = failure; await openDelete("A");
    await confirm.click(); await modal.getByRole("alert").waitFor();
    assert.equal(await confirm.isEnabled(), true); await sameDraft(text);
    await modal.getByRole("button", { name: "取消", exact: true }).click();
    assert.match(page.url(), /session=a/);
  }
  assert.equal(requests, 2);
  pass("HTTP 500 and network failure keep current session/text/image and leave dialog retry/cancel usable");

  deletion = "200"; const releaseSuccess = gateDeletion();
  await openDelete("A"); const before = confirmations;
  await confirm.evaluate(el => { el.click(); el.click(); }); await waitRequests(3); await tick();
  assert.equal(confirmations, before + 1); await sameDraft(text);
  assert.equal(await modal.getByRole("button", { name: "处理中…", exact: true }).isDisabled(), true);
  await page.keyboard.press("Escape"); assert.equal(await modal.isVisible(), true);
  releaseSuccess(); await page.waitForURL(url => url.searchParams.get("session") !== "a"); await waitInput();
  assert.equal(await input.inputValue(), ""); assert.equal(await page.getByRole("button", { name: /删除图片/ }).count(), 0);
  assert.equal(await page.evaluate(() => window.__revoked.length), 1); assert.equal(requests, 3);
  pass("successful deletion alone clears/revokes once and navigates; duplicate clicks stay one request and busy Escape cannot interrupt");

  await page.getByRole("link", { name: "对话 B", exact: true }).click(); await page.waitForURL("**session=b"); await waitInput();
  await input.fill("旧的草稿"); await attach();
  const releaseNewer = gateDeletion(); await openDelete("B"); await confirm.click(); await waitRequests(4);
  // Native modality blocks manual edits; injected input models a newer React draft arriving during the request.
  await input.evaluate(el => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(el, "后来输入的新推导");
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }); await tick();
  assert.equal(await input.inputValue(), "后来输入的新推导");
  releaseNewer(); await modal.waitFor({ state: "hidden" });
  await page.getByText("对话已移入垃圾桶，新的草稿与当前页面已保留。", { exact: true }).waitFor();
  assert.match(page.url(), /session=b/); await sameDraft("后来输入的新推导", 1);
  pass("late success cannot clear or unmount a newer text/image draft; deleted result is disclosed while the draft stays usable");

  // Continue via ordinary guarded navigation to verify the synchronous compatibility path.
  await page.getByRole("link", { name: "对话 C", exact: true }).click(); await page.waitForURL("**session=c"); await waitInput();
  await input.fill("资料范围与推导都未提交");
  await page.getByRole("button", { name: "当前对话的学习资料", exact: true }).click();
  await page.getByRole("checkbox", { name: "参考库 1", exact: true }).check();
  await tick();
  const releaseScope = gateDeletion(); await openDelete("C"); const beforeCombined = confirmations;
  await confirm.click(); await waitRequests(5);
  assert.equal(confirmations, beforeCombined + 1); assert.match(confirmationMessage, /未发送/); assert.match(confirmationMessage, /参考范围尚未应用/);
  await page.getByRole("checkbox", { name: "参考库 2", exact: true }).evaluate(el => el.click()); await tick();
  releaseScope(); await modal.waitFor({ state: "hidden" });
  assert.match(page.url(), /session=c/); assert.equal(await input.inputValue(), "资料范围与推导都未提交");
  assert.equal(await page.getByRole("checkbox", { name: "参考库 2", exact: true }).isChecked(), true);
  pass("message and scope share one confirmation; a newer scope configuration invalidates old permission even when its warning text is unchanged");

  await page.screenshot({ path: path.join(output, "preserved-newer-draft.png"), fullPage: true });
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "results.json"), JSON.stringify({ checks, errors, requests, confirmations }, null, 2));
  console.log(`Evidence: ${output}`);
} catch (error) {
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true });
  console.error(`Failure evidence: ${output}`); throw error;
} finally { await browser.close(); }

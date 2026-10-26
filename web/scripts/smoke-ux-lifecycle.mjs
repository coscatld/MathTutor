// Real React interactions with isolated API/WS fault injection. No model calls.
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const base = process.env.LAYOUT_URL || "http://127.0.0.1:3000";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-ux-browser-"));
const checks = [], errors = [];
const pass = name => { checks.push(name); console.log(`PASS ${name}`); };
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
page.on("pageerror", error => errors.push(error.message));
await page.addInitScript(() => {
  window.__sockets = []; window.__manualOpen = false; window.__revoked = [];
  const revoke = URL.revokeObjectURL;
  URL.revokeObjectURL = value => { window.__revoked.push(value); revoke(value); };
  window.__acceptTimers = []; window.__aborts = 0;
  const nativeFetch = window.fetch;
  window.fetch = (url, init) => {
    if (init?.signal) init.signal.addEventListener("abort", () => window.__aborts++);
    return nativeFetch(url, init);
  };
  const nativeTimeout = window.setTimeout.bind(window);
  window.setTimeout = (fn, delay, ...args) => {
    if (delay === 20000) window.__acceptTimers.push(fn);
    return nativeTimeout(fn, delay, ...args);
  };
  const NativeSocket = window.WebSocket;
  class Socket {
    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
    readyState = 0; sent = []; closes = 0;
    constructor(url, protocols) {
      if (!String(url).includes("/api/v2/math-tutor/ws")) return new NativeSocket(url, protocols);
      this.url = url; window.__sockets.push(this);
      if (!window.__manualOpen) nativeTimeout(() => this.open(), 20);
    }
    open() { if (this.readyState === 3) return; this.readyState = 1; this.onopen?.({}); }
    send(value) { this.sent.push(JSON.parse(value)); }
    frame(value) { this.onmessage?.({data: JSON.stringify(value)}); }
    close() { this.readyState = 3; this.closes++; this.onclose?.({}); }
  }
  window.WebSocket = Socket;
});
const settings = { is_configured: true, onboarding_completed: true, provider_configs: {} };
const session = { cycle_id: "cycle-a", problem_revision: "revision-1", state_version: 1, state: "awaiting_attempt", allowed_next_inputs: ["send_message", "submit_attempt", "accept_practice_offer"], messages: [{ role: "tutor", content: "请独立完成这一步。" }], problem_context: { problem_id: "problem-a", display_text: "解方程 2x=4", lifecycle: "ACTIVE", skill_ids: [] } };
const mount = { space_ids: [], document_ids: [], only_selected: false, mode: "tutor", save_space_id: "", tool_mode: "native", available_documents: [], effective_document_ids: [] };
const offer = { offer_id: "offer", parent_cycle_id: "parent", status: "ACTIVE", skill_labels: ["方程"], concept_labels: [], difficulty: "1", offered_at: "2026-10-26T00:00:00Z", expires_at: "2026-10-27T00:00:00Z", display_status: "pending" };
let authStatus = 200, authCalls = 0, resyncFailure = false, childFailure = false, childGate, parentGate;
let nativeStatus = 501, scopeStatus = 500, refreshFailure = false, importStatus = "ready", retrieval = true;
let docs = [], pickerCalls = 0, imports = 0, patches = 0, parentReads = 0, childReads = 0, pickers = 0;
page.on("filechooser", () => { pickers++; });
const makeDoc = () => ({document_id: `doc-${imports}`, filename: `fixture-${imports}.pdf`, mime_type: "application/pdf", status: importStatus, retrieval_enabled: retrieval, chunk_count: ["ready", "ready_with_warnings"].includes(importStatus) ? 2 : 0, page_count: 2, size_bytes: 8, image_count: 0, empty_page_count: 0, parse_warning: importStatus === "ready_with_warnings" ? "第 2 页为空" : null, error: null, created_at: "2026-10-26T00:00:00Z", is_global: false, conversation_ids: []});
await page.route("**/api/**", async route => {
  const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method();
  const reply = (json, status = 200) => route.fulfill({status, json});
  if (p.endsWith("/auth/status")) {authCalls++; return reply(authStatus === 200 ? {enabled:false,authenticated:true} : {detail:"fixture rejected"}, authStatus);}
  if (p.endsWith("/bootstrap")) return reply({phase:"READY",readiness:"READY",steps:[]});
  if (p.endsWith("/settings/embedding")) return reply({status:"disabled",status_label:"关键词检索"});
  if (p.endsWith("/settings")) return reply(settings);
  if (p.endsWith("/sessions")) return reply([{conversation_id:"a",title:"对话 A"},{conversation_id:"b",title:"对话 B"}]);
  if (p.includes("/sessions/")) return reply(resyncFailure ? {detail:"offline"} : session, resyncFailure ? 503 : 200);
  if (p.endsWith("/cycles/parent")) {parentReads++; if (parentGate) await parentGate; return reply({session_id:"parent-session"});}
  if (p.endsWith("/cycles/child")) {childReads++; if (childGate) await childGate; return reply(childFailure ? {detail:"offline"} : {session_id:"child-session"},childFailure?503:200);}
  if (p.endsWith("/offers")) return reply([offer]);
  if (p.endsWith("/resume")) return reply({session_id:"child-session"});
  if (p.endsWith("/knowledge/libraries")) return reply([{space_id:"lib",name:"参考库",kind:"course",enabled:1}]);
  if (p.includes("/knowledge/conversations/")) return reply(method === "POST" ? {...mount,...request.postDataJSON()} : mount);
  if (p.endsWith("/resources")) return reply({documents:[],images:[],message_count:1,scope:mount});
  if (p.endsWith("/image-capabilities")) return reply({vision:false});
  if (p.endsWith("/documents/pick")) {
    pickerCalls++;
    if (nativeStatus !== 200) return reply({detail:"fixture picker"},nativeStatus);
    imports++; const doc=makeDoc(); docs.push(doc); return reply({status:"imported",document:doc});
  }
  if (p.endsWith("/documents/import")) {imports++; const doc=makeDoc(); docs.push(doc); return reply(doc);}
  if (p.endsWith("/scope") && method === "PATCH") {
    patches++; if (scopeStatus !== 200) return reply({detail:"scope failed"},scopeStatus);
    const doc=docs.find(doc=>p.includes(doc.document_id)); doc.is_global=true; return reply(doc);
  }
  if (p.endsWith("/documents")) return reply(refreshFailure ? {detail:"refresh failed"} : docs,refreshFailure?503:200);
  return reply([]);
});
const input = page.getByRole("textbox", {name:"聊天输入"});
const tick = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const waitEnabled = async locator => { await locator.waitFor(); await page.waitForFunction(selector => !document.querySelector(selector)?.disabled, await locator.evaluate(el => {el.dataset.uxWait="true";return '[data-ux-wait="true"]';})); await locator.evaluate(el=>delete el.dataset.uxWait); };
const clickStart = async () => { const button=page.getByRole("button",{name:"开始练习",exact:true}); await button.waitFor(); await button.evaluate(el=>{el.click();el.click();}); };
const sendFrame = async frame => page.evaluate(value=>window.__sockets.at(-1).frame(value),frame);
try {
  authStatus=403;
  await page.goto(`${base}/`);
  await page.getByText(/访问被来源校验拒绝/).waitFor();
  const rejectedCalls=authCalls; await page.waitForTimeout(1700); assert.equal(authCalls,rejectedCalls);
  pass("403 classified, no automatic retry");
  authStatus=503;
  await page.getByRole("button",{name:"重新检查"}).click();
  await page.getByText("本地 MathTutor 服务还没有准备好。").waitFor();
  authStatus=200;
  await page.waitForURL(/\/math-tutor/);
  pass("temporary service failure retries and recovers");

  await page.goto(`${base}/math-tutor?session=a`); await waitEnabled(input);
  await input.fill("第一步：2x=4\n第二步：x=2");
  await input.evaluate(el=>{el.setSelectionRange(4,4);el.focus();});
  await page.locator('input[type="file"][accept="image/png,image/jpeg,image/webp"]').setInputFiles({name:"step.png",mimeType:"image/png",buffer:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==","base64")});
  let dialogs=0;
  const dismiss = dialog=>{dialogs++;void dialog.dismiss();}; page.on("dialog",dismiss);
  await page.getByRole("link",{name:"对话 B",exact:true}).click();
  assert.equal(dialogs,1); assert.match(page.url(),/session=a/); assert.match(await input.inputValue(),/第二步/);
  assert.equal(await input.evaluate(el=>el.selectionStart),4);
  assert.equal(await input.evaluate(el=>el===document.activeElement),true);
  assert.equal(await page.getByRole("button",{name:/删除图片/}).count(),1);
  await page.getByRole("button",{name:"新建对话",exact:true}).click(); assert.equal(dialogs,2);
  await page.getByRole("link",{name:"题库",exact:true}).click(); assert.equal(dialogs,3);
  // An image send failure retains the same guarded draft.
  await page.getByRole("button",{name:"发送",exact:true}).click();
  await page.getByRole("button",{name:"重试发送",exact:true}).waitFor();
  await page.getByRole("link",{name:"对话 B",exact:true}).click(); assert.equal(dialogs,4);
  // Both unsaved scope and message participate in a single dialog.
  await page.getByRole("button",{name:"当前对话的学习资料",exact:true}).click();
  await page.getByRole("checkbox",{name:"参考库",exact:true}).check();
  let combined=""; const inspectDialog=d=>{combined=d.message();}; page.on("dialog",inspectDialog);
  await page.getByRole("link",{name:"对话 B",exact:true}).click();
  assert.equal(dialogs,5); assert.match(combined,/未发送/); assert.match(combined,/参考范围尚未应用/);
  page.off("dialog",inspectDialog); page.off("dialog",dismiss);
  page.once("dialog",d=>d.accept()); await page.getByRole("link",{name:"对话 B",exact:true}).click();
  await page.waitForURL("**session=b"); await waitEnabled(input); assert.equal(await input.inputValue(),"");
  assert.equal(await page.evaluate(()=>window.__revoked.length),1);
  pass("draft guard: session/new/question bank, failed send, one combined dialog, cancel preserves cursor/image, discard revokes once");
  page.on("dialog", dialog => dialog.accept());
  // No dirty content, no confirmation.
  await page.getByRole("link",{name:"对话 A",exact:true}).click(); await page.waitForURL("**session=a"); await waitEnabled(input);
  await page.getByRole("button",{name:"我来写",exact:true}).click(); await input.fill("x=2"); await tick();
  await sendFrame({event_type:"cycle_state_committed",cycle_id:"cycle-b",problem_revision:"revision-2",cycle_state_version:2,allowed_next_inputs:["submit_attempt","send_message"],payload:{}});
  await page.getByText(/这是旧题草稿/).waitFor();
  assert.equal(await page.locator(".mt-send-button").isDisabled(),true);
  await page.getByRole("button",{name:"丢弃旧题草稿"}).click();
  pass("old cycle/revision draft cannot submit to the new problem; empty draft navigation needs no confirmation");

  await page.goto(`${base}/math-tutor/offers`);
  await page.evaluate(()=>{window.__manualOpen=true;});
  let releaseParent; parentGate=new Promise(resolve=>{releaseParent=resolve;});
  const readsBefore=parentReads; await clickStart();
  await page.waitForFunction(()=>document.querySelector('button')!==null); await tick();
  assert.equal(parentReads,readsBefore+1); assert.equal(await page.getByRole("button",{name:"正在处理…",exact:true}).isDisabled(),true);
  releaseParent(); parentGate=undefined;
  await page.waitForFunction(()=>window.__sockets.length===1);
  assert.equal(await page.getByRole("button",{name:"正在处理…",exact:true}).isDisabled(),true);
  await page.evaluate(()=>window.__sockets[0].open());
  let releaseChild; childGate=new Promise(resolve=>{releaseChild=resolve;});
  const frame={event_type:"cycle_state_committed",extra:{child_cycle_id:"child"}};
  await sendFrame(frame); await sendFrame(frame); await tick(); assert.equal(childReads,1);
  assert.equal(await page.getByRole("button",{name:"正在处理…",exact:true}).isDisabled(),true);
  childFailure=true; releaseChild(); childGate=undefined;
  await page.getByRole("alert").filter({hasText:"练习已接受"}).waitFor();
  assert.equal(await page.evaluate(()=>window.__sockets[0].closes),1);
  // Old timeout callback cannot affect the next operation.
  await clickStart(); await page.waitForFunction(()=>window.__sockets.length===2);
  await page.evaluate(()=>window.__acceptTimers[0]());
  assert.equal(await page.evaluate(()=>window.__sockets[1].readyState),0);
  await page.evaluate(()=>window.__sockets[1].open()); await sendFrame({event_type:"turn_error",payload:{error:"fixture"}});
  await page.getByRole("alert").filter({hasText:"辅导服务未能接受"}).waitFor();
  await clickStart(); await page.waitForFunction(()=>window.__sockets.length===3);
  await page.getByRole("link",{name:"资料",exact:true}).click();
  await page.waitForURL("**/documents");
  assert.equal(await page.evaluate(()=>window.__sockets[2].readyState),3);
  // Abort a pending GET on SPA unmount, then release it: no late socket.
  await page.getByRole("link",{name:"推荐练习",exact:true}).click();
  let releasePending; parentGate=new Promise(resolve=>{releasePending=resolve;});
  const readsAtCancel=parentReads; await clickStart();
  await page.waitForResponse(response=>false,{timeout:100}).catch(()=>{});
  assert.equal(parentReads,readsAtCancel+1);
  const abortsBefore=await page.evaluate(()=>window.__aborts);
  await page.getByRole("link",{name:"资料",exact:true}).click(); await page.waitForURL("**/documents");
  assert.ok(await page.evaluate(()=>window.__aborts)>abortsBefore);
  releasePending(); parentGate=undefined; await tick();
  assert.equal(await page.evaluate(()=>window.__sockets.length),3);
  await page.getByRole("link",{name:"推荐练习",exact:true}).click();
  resyncFailure=true; await clickStart(); await page.getByRole("alert").filter({hasText:"辅导状态同步失败"}).waitFor();
  assert.equal(await page.evaluate(()=>window.__sockets.length),3);
  resyncFailure=false; childFailure=false;
  await clickStart(); await page.waitForFunction(()=>window.__sockets.length===4);
  await page.evaluate(()=>window.__sockets[3].open()); await sendFrame(frame);
  await page.waitForURL("**session=child-session");
  await page.getByRole("link",{name:"资料",exact:true}).click(); await page.waitForURL("**/documents");
  pass("offer: duplicate click lock through GET/WS/child GET, single child lookup, late timeout isolation, public error termination, GET abort/unmount cleanup, sync failure classification, successful child navigation");

  const add=page.getByRole("button",{name:"添加资料",exact:true}); await waitEnabled(add);
  await page.getByRole("combobox",{name:"新资料保存到"}).selectOption("global");
  const beforePickers=pickers;
  nativeStatus=422; await add.click(); await page.getByText("fixture picker",{exact:true}).waitFor();
  assert.equal(pickers,beforePickers); assert.equal(imports,0);
  nativeStatus=501; const chooser=page.waitForEvent("filechooser"); await add.click();
  await (await chooser).setFiles({name:"fixture.pdf",mimeType:"application/pdf",buffer:Buffer.from("fixture")});
  await page.getByRole("button",{name:"重试设为总资料",exact:true}).waitFor();
  await page.locator("#document-doc-1").waitFor(); assert.equal(imports,1); assert.equal(patches,1);
  scopeStatus=200; await page.getByRole("button",{name:"重试设为总资料",exact:true}).click();
  await page.locator("#document-doc-1").getByText("共享范围：所有对话",{exact:true}).waitFor();
  assert.equal(imports,1); assert.equal(patches,2); assert.equal(pickers,beforePickers+1);
  pass("documents: 422 never reopens picker, 501 fallback, scope failure preserves row, retry only PATCHes");

  nativeStatus=200; refreshFailure=true;
  await add.click(); await page.getByText(/资料已保存，但列表刷新失败/).waitFor();
  await page.locator("#document-doc-2").waitFor(); assert.equal(pickers,beforePickers+1);
  pass("native import success with failed refresh remains saved and visible");
  refreshFailure=false; await page.getByRole("combobox",{name:"新资料保存到"}).selectOption("");
  for (const [status,enabled,expected] of [["ready",true,"关联对话或设为总资料后可检索"],["ready_with_warnings",true,"第 2 页为空"],["needs_ocr",false,"当前不可检索"],["failed",false,"解析失败"],["ready",false,"检索已停用"]]) {
    importStatus=status; retrieval=enabled;
    await waitEnabled(add);
    nativeStatus = status === "needs_ocr" || !enabled ? 501 : 200;
    if (nativeStatus === 501) {
      const picker=page.waitForEvent("filechooser"); await add.click();
      await (await picker).setFiles({name:"status.pdf",mimeType:"application/pdf",buffer:Buffer.from("fixture")});
    } else await add.click();
    const row=page.locator(`#document-doc-${imports}`); await row.waitFor();
    await row.getByText(new RegExp(expected)).first().waitFor();
    const toast=page.locator('[role="status"]').filter({has:page.getByRole("button",{name:"关闭通知"})});
    await toast.getByText(new RegExp(expected)).first().waitFor();
    await toast.getByRole("button",{name:"查看资料",exact:true}).click();
    assert.equal(await row.evaluate(el=>el===document.activeElement),true);
  }
  await page.screenshot({path:path.join(output,"documents.png"),fullPage:true});
  pass("ready/warnings/OCR/failed/disabled/unassigned feedback matches rows; toast focuses recovery controls");
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  await page.setViewportSize({width:375,height:812});
  await page.evaluate(()=>document.documentElement.classList.add("dark"));
  await tick();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(output,"documents-mobile-dark.png"),fullPage:true});
  assert.deepEqual(errors,[]);
  await writeFile(path.join(output,"results.json"),JSON.stringify({checks,errors},null,2));
  console.log(`Evidence: ${output}`);
} catch(error) {
  await page.screenshot({path:path.join(output,"failure.png"),fullPage:true});
  console.error(`Failure evidence: ${output}`); throw error;
} finally { await browser.close(); }

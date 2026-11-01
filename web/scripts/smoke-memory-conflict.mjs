// Two real React pages share a synthetic versioned memory API. No model calls.
import assert from "node:assert/strict";
import {mkdtemp,writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE,args:["--no-proxy-server"]});
const context=await browser.newContext({viewport:{width:1280,height:1000},reducedMotion:"reduce"});
const base=process.env.LAYOUT_URL||"http://127.0.0.1:3198";
const output=await mkdtemp(path.join(tmpdir(),"mathtutor-memory-conflict-"));
const errors=[],checks=[],writes=[];
let version=1,held=null,holdNextEdit=false;
const stamp=()=>`2026-10-30T01:00:00.${String(version++).padStart(6,"0")}+00:00`;
const row=(id,source,value)=>({memory_id:id,memory_type:"user_note",subject:"我",predicate:"内容",object_json:{value},source_type:source,confidence:.9,retrieval_enabled:source!=="MODEL_INFERRED",created_at:"2026-10-30T00:00:00+00:00",updated_at:stamp()});
const explicitId="00000000-0000-0000-0000-000000000001",inferredId="00000000-0000-0000-0000-000000000002";
const rows=new Map([[explicitId,row(explicitId,"USER_EXPLICIT","用户原文：偏好具体例子")],[inferredId,row(inferredId,"MODEL_INFERRED","待确认的原始推测")]]);
const pass=name=>{checks.push(name);console.log("PASS "+name);};
async function respond(route,input,id,suffix){
 const current=rows.get(id);
 if(input.expected_updated_at!==current.updated_at){await route.fulfill({status:409,json:{detail:"这条记忆已在其他位置更新。",code:"memory_conflict",latest:current}});return;}
 const next={...current,updated_at:stamp()};
 if(suffix==="retrieval")next.retrieval_enabled=input.enabled;
 else if(suffix==="confirm")next.source_type="USER_CONFIRMED";
 else {next.object_json=input.object_json;next.predicate=input.predicate||current.predicate;}
 rows.set(id,next);await route.fulfill({json:next});
}
await context.route("**/api/**",async route=>{
 const req=route.request(),p=new URL(req.url()).pathname;
 let json=[];
 if(p.endsWith("/auth/status"))json={enabled:false,authenticated:true};
 else if(p.endsWith("/bootstrap"))json={phase:"READY",readiness:"READY",steps:[]};
 else if(p.endsWith("/settings"))json={preset_id:"custom",model:"fixture",is_configured:true,onboarding_completed:true,key_masked:"••••1234"};
 else if(p.endsWith("/memory"))json=[...rows.values()];
 else if(p.includes("/memory/")){
  const [,id,suffix=""]=p.match(/\/memory\/([^/]+)(?:\/(.*))?$/);
  const input=req.postDataJSON();writes.push({id,suffix,version:input.expected_updated_at});
  if(holdNextEdit&&req.method()==="PUT"){holdNextEdit=false;held={route,input,id,suffix};return;}
  await respond(route,input,id,suffix);return;
 }
 await route.fulfill({json});
});
context.on("page",page=>{page.setDefaultTimeout(15000);page.on("pageerror",error=>errors.push(error.message));});
async function waitHeld(){const deadline=Date.now()+10000;while(!held){assert.ok(Date.now()<deadline,"edit did not reach API barrier");await new Promise(r=>setTimeout(r,10));}return held;}
function memory(page,id){return page.locator(`li[data-memory-id="${id}"]`);}
async function open(page){await page.goto(base+"/math-tutor/memory");await page.getByRole("heading",{name:/我的记忆|My memories/,exact:true}).waitFor();await page.locator("li.mt-card").first().waitFor();}
try{
 const first=await context.newPage(),second=await context.newPage();await open(first);await open(second);
 let a=memory(first,explicitId),b=memory(second,explicitId);
 await a.getByRole("button",{name:"编辑这条记忆",exact:true}).click();
 const input=first.getByRole("textbox",{name:"记忆内容",exact:true});await input.fill("窗口 A 的编辑草稿");
 holdNextEdit=true;await a.getByRole("button",{name:"保存",exact:true}).click();await waitHeld();
 await b.getByRole("checkbox",{name:"允许用于辅导",exact:true}).click();
 await second.waitForFunction(()=>!document.querySelector('li.mt-card input[type="checkbox"]')?.checked);
 assert.equal(rows.get(explicitId).retrieval_enabled,false);
 await respond(held.route,held.input,held.id,held.suffix);held=null;
 await first.getByRole("group",{name:"记忆版本冲突",exact:true}).waitFor();
 assert.equal(await input.inputValue(),"窗口 A 的编辑草稿");assert.equal(rows.get(explicitId).object_json.value,"用户原文：偏好具体例子");
 await first.getByRole("button",{name:"保留草稿，按最新版本继续编辑",exact:true}).click();
 await a.getByRole("button",{name:"保存",exact:true}).click();await input.waitFor({state:"hidden"});
 a=memory(first,explicitId);assert.equal(await a.getByRole("checkbox").isChecked(),false);
 assert.equal(rows.get(explicitId).retrieval_enabled,false);
 pass("two-window disable versus edit returns a conflict, keeps the draft and only resaves after review without reenabling retrieval");

 const inferredSecond=memory(second,inferredId);await inferredSecond.getByRole("button",{name:"编辑这条记忆",exact:true}).click();
 await second.getByRole("textbox",{name:"记忆内容",exact:true}).fill("已在另一窗口修订的推测");
 await inferredSecond.getByRole("button",{name:"保存",exact:true}).click();await second.getByRole("textbox",{name:"记忆内容",exact:true}).waitFor({state:"hidden"});
 let inferredFirst=memory(first,inferredId);await inferredFirst.getByRole("button",{name:"确认",exact:true}).click();
 await first.getByText("这条记忆已变更，请检查最新内容后再确认。",{exact:true}).waitFor();
 assert.equal(rows.get(inferredId).source_type,"MODEL_INFERRED");assert.equal(rows.get(inferredId).retrieval_enabled,false);
 inferredFirst=memory(first,inferredId);await inferredFirst.getByRole("button",{name:"确认",exact:true}).click();
 await first.getByText("已确认这条记忆，检索开关保持原设置。",{exact:true}).waitFor();
 assert.equal(rows.get(inferredId).source_type,"USER_CONFIRMED");assert.equal(rows.get(inferredId).retrieval_enabled,false);
 pass("confirmation of a stale inference requires another explicit review and never enables a disabled record");

 a=memory(first,explicitId);await a.getByRole("button",{name:"编辑这条记忆",exact:true}).click();await input.fill("本次提交");
 holdNextEdit=true;await a.getByRole("button",{name:"保存",exact:true}).click();await waitHeld();
 assert.ok(await a.getByRole("button",{name:"取消",exact:true}).isDisabled());
 assert.ok(await a.getByRole("button",{name:"编辑这条记忆",exact:true}).isDisabled());
 await input.fill("等待期间的新输入");await respond(held.route,held.input,held.id,held.suffix);held=null;
 await first.getByText("上次提交已保存，当前仍有未保存修改。",{exact:true}).waitFor();
 assert.equal(await input.inputValue(),"等待期间的新输入");
 await a.getByRole("button",{name:"保存",exact:true}).click();await input.waitFor({state:"hidden"});
 assert.equal(rows.get(explicitId).object_json.value,"等待期间的新输入");assert.equal(rows.get(explicitId).retrieval_enabled,false);
 pass("edits made while a save waits remain dirty and retry with the confirmed server version");

 await first.evaluate(()=>localStorage.setItem("mathtutor-language","en"));await open(first);await open(second);
 a=memory(first,explicitId);b=memory(second,explicitId);
 await a.getByRole("button",{name:"Edit this memory",exact:true}).click();
 const englishInput=first.getByRole("textbox",{name:"Memory content",exact:true});await englishInput.fill("Keep this draft");
 await b.getByRole("button",{name:"Edit this memory",exact:true}).click();await second.getByRole("textbox",{name:"Memory content",exact:true}).fill("最新内容保持中文原文");
 await b.getByRole("button",{name:"Save",exact:true}).click();await second.getByRole("textbox",{name:"Memory content",exact:true}).waitFor({state:"hidden"});
 await a.getByRole("button",{name:"Save",exact:true}).click();await first.getByRole("group",{name:"Memory version conflict",exact:true}).waitFor();
 assert.equal(await englishInput.inputValue(),"Keep this draft");
 await first.setViewportSize({width:375,height:900});await first.getByRole("group",{name:"Memory version conflict",exact:true}).scrollIntoViewIfNeeded();
 assert.ok(await first.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await first.screenshot({path:path.join(output,"memory-conflict-english-mobile.png"),fullPage:false});
 await first.getByRole("button",{name:"Discard draft and load the latest content",exact:true}).click();
 assert.equal(await englishInput.inputValue(),"最新内容保持中文原文");
 pass("English conflict recovery fits 375px, preserves original content and loads the latest text only after explicit discard");
 assert.deepEqual(errors,[]);assert.ok(writes.every(item=>typeof item.version==="string"&&item.version.includes(".000")));
 await writeFile(path.join(output,"results.json"),JSON.stringify({status:"PASS",checks,errors,writeCount:writes.length,scope:"Actual macOS Chromium; two pages and controlled versioned REST fixtures; no model calls."},null,2));
 console.log("Evidence: "+output);
}catch(error){const page=context.pages()[0];if(page)await page.screenshot({path:path.join(output,"failure.png"),fullPage:true});console.error("Evidence: "+output);throw error;}
finally{await browser.close();}

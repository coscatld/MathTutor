// Real React controls with isolated REST/WS fixtures; no model/student data.
import assert from "node:assert/strict";
import {mkdtemp, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true});
const output=await mkdtemp(path.join(tmpdir(),"mathtutor-response-modes-"));
const page=await browser.newPage({viewport:{width:1280,height:900},reducedMotion:"reduce"});
const errors=[],sent=[],checks=[];
page.on("pageerror",e=>errors.push(e.message));
const pass=name=>{checks.push(name);console.log("PASS "+name);};
const choices={format:"single_choice",version:"v1",options:[{id:"A",text:"1"},{id:"B",text:"2"},{id:"C",text:"3"},{id:"D",text:"4"}]};
let summary={cycle_id:"child",problem_revision:"revision",state_version:3,state:"awaiting_attempt",allowed_next_inputs:["submit_attempt","request_options"],problem_context:{problem_id:"p",display_text:"解方程 2x=4",skill_ids:[],lifecycle:"ACTIVE",response_mode:"free_response",observation_kind:"independent_transfer",options_exposed:false,current_subgoal:{id:"answer",prompt_target:"写出答案",status:"pending"}},messages:[{role:"tutor",content:"请先独立尝试这道新题。"}]};
await page.route("**/api/**",route=>{
 const p=new URL(route.request().url()).pathname;
 let body=[];
 if(p.endsWith("/auth/status"))body={enabled:false,authenticated:true};
 else if(p.endsWith("/bootstrap"))body={phase:"READY",readiness:"READY",steps:[]};
 else if(p.endsWith("/settings"))body={is_configured:true,onboarding_completed:true,provider_configs:{}};
 else if(p.endsWith("/sessions"))body=[{conversation_id:"transfer",title:"迁移练习"}];
 else if(p.includes("/sessions/"))body=summary;
 else if(p.endsWith("/resources"))body={documents:[],images:[],message_count:1};
 else if(p.endsWith("/offers"))body=[{offer_id:"o",parent_cycle_id:"p",status:"ACCEPTED",skill_labels:["方程"],concept_labels:[],difficulty:"2",offered_at:"2026-10-28T00:00:00Z",expires_at:"",display_status:"completed",response_mode:"single_choice",observation_kind:"diagnostic",result_summary:{independent_correct:0,first_free_response:0,diagnostic_correct:1,helped:0,observations:1}}];
 return route.fulfill({json:body});
});
let socket;
await page.routeWebSocket("**/api/**",ws=>{socket=ws;ws.onMessage(raw=>sent.push(JSON.parse(raw)));});
const frame=(type,context=summary.problem_context)=>socket.send(JSON.stringify({event_type:type,cycle_id:"child",problem_revision:"revision",cycle_state:"awaiting_attempt",cycle_state_version:3,allowed_next_inputs:summary.allowed_next_inputs,problem_context:context,payload:{}}));
try{
 const base=process.env.LAYOUT_URL || "http://127.0.0.1:3198";
 await page.goto(base+"/math-tutor?session=transfer");
 await page.getByText("正在写本题步骤 · 发送后检查这一步",{exact:true}).waitFor();
 assert.equal(await page.getByRole("radio").count(),0);
 const input=page.getByRole("textbox",{name:"聊天输入",exact:true});
 await input.fill("x=2");
 await page.getByRole("button",{name:"提交本题步骤",exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('textarea')?.disabled===true);
 assert.equal(sent.at(-1).command,"submit_attempt");assert.equal(sent.at(-1).payload.answer,"x=2");
 frame("turn_end");
 pass("new transfer opens in bound free-response mode without option payload or radios");
 const expose=page.getByRole("button",{name:"显示选项（转为诊断）",exact:true});
 await expose.click();
 assert.equal(sent.at(-1).command,"request_options");
 summary={...summary,allowed_next_inputs:["submit_attempt"],problem_context:{...summary.problem_context,choices,options_exposed:true,observation_kind:"diagnostic"}};
 frame("cycle_state_committed");frame("turn_end");
 await page.getByRole("region",{name:"选择题诊断"}).waitFor();
 assert.equal(await page.getByRole("radio").count(),4);
 await page.getByText(/已查看选项，本题后续作答记为诊断/).waitFor();
 await page.reload();
 await page.getByRole("region",{name:"选择题诊断"}).waitFor();
 assert.equal(await page.getByRole("radio").count(),4);
 pass("explicit options request and reload preserve diagnostic explanation and choices");
 await page.goto(base+"/math-tutor/offers");
 await page.getByText(/1 次诊断选择答对/).waitFor();
 for(const width of [320,375,768]){
  await page.setViewportSize({width,height:900});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"result card fits "+width);
 }
 await page.screenshot({path:path.join(output,"diagnostic-result.png"),fullPage:true});
 pass("completed card shows diagnostic success and next step across narrow widths");
 assert.deepEqual(errors,[]);
 await writeFile(path.join(output,"results.json"),JSON.stringify({checks,errors,scope:"macOS Chromium, isolated REST/WS fixtures"},null,2));
 console.log("Evidence: "+output);
}finally{await browser.close();}

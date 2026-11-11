// Browser behavior QA uses synthetic API fixtures, never a learner's data.
import assert from "node:assert/strict";
import {mkdir, mkdtemp, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const output = process.env.LOOP_QA_OUTPUT || await mkdtemp(path.join(tmpdir(),"mathtutor-loop-"));
await mkdir(output,{recursive:true});
const browser = await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE});
const page = await browser.newPage();
const errors=[]; page.on("pageerror",error=>errors.push(error.message));
const domain="fraction_addition";
const makeQuestion=(id,statement,purpose="review")=>({probe_id:id,domain,family:"fixture",purpose,statement,prompt_zh:"计算并填写结果。",prompt_en:"Calculate and enter the answer."});
const q1=makeQuestion("d1","1/2 + 1/3","diagnostic"),q2=makeQuestion("r1","1/6 + 1/7"),q3=makeQuestion("r2","2/7 + 3/7"),q4=makeQuestion("r3","3/8 + 1/4"),q5=makeQuestion("t1","x + 1/6 = 1/7","transfer");
let episode=null, loseResponse=true, due=false; const receipts=new Map(), answerIds=[];
const envelope=()=>({schema_version:"learning_loop_v1",server_time:"2026-11-11T06:00:00Z",domains:[
 {domain,label_zh:"分数加法",label_en:"Adding fractions",episode:episode?{...episode,can_start:episode.phase==="waiting"&&due}:null},
 {domain:"signed_subtraction",label_zh:"有符号减法",label_en:"Signed subtraction",episode:null}]});
const feedback=(kind,q,extra={})=>({kind,probe_id:q.probe_id,statement:q.statement,...extra});
await page.route("**/api/**",async route=>{
 const request=route.request(),url=new URL(request.url());let body=[];
 if(url.pathname.endsWith("/auth/status"))body={enabled:false,authenticated:true};
 else if(url.pathname.endsWith("/bootstrap"))body={phase:"READY",readiness:"READY",steps:[]};
 else if(url.pathname.endsWith("/sessions"))body=[];
 else if(url.pathname.endsWith("/settings"))body={is_configured:true,onboarding_completed:true,preset_id:"custom",model:"fixture",base_url:"",key_masked:null};
 else if(url.pathname.endsWith("/presets"))body=[];
 else if(url.pathname.endsWith("/student-summary"))body={skills:[],total_attempts:0,active_misconceptions:0,has_conversations:false,has_independent_evidence:false};
 else if(url.pathname.endsWith("/stage-review"))body={status:"idle",preferences:{},review:null};
 else if(url.pathname.includes("/learning-loop")){
  const action=url.pathname.split("/").at(-1),data=request.method()==="POST"?request.postDataJSON():null;
  if(action==="start"){
   if(!episode)episode={episode_id:"fixture-episode",domain,phase:"diagnose",question:q1,due_at:null,can_start:false,review_round:0,
    diagnostic:{status:"collecting",answered:0,label_zh:"继续用新题检查。",label_en:"Continue with a fresh problem."},
    evidence:{independent_practice:0,delayed_review:0,structural_transfer:0},feedback:null};
   else if(episode.phase==="waiting"&&due){episode={...episode,phase:"review",question:q4,feedback:null};due=false;}
  }else if(action==="answer"||action==="help"){
   if(action==="answer")answerIds.push(data.request_id);
   if(!receipts.has(data.request_id)){
    const q=episode.question;
    assert.equal(data.episode_id,episode.episode_id);assert.equal(data.probe_id,q.probe_id);
    if(action==="help")episode={...episode,feedback:feedback("help",q,{answer:"13/42",explanation_zh:"先通分。",explanation_en:"Use a common denominator.",independent:false})};
    else if(data.answer==="?")episode={...episode,feedback:feedback("unknown",q)};
    else if(q.probe_id==="d1")episode={...episode,phase:"practice",question:q2,diagnostic:{...episode.diagnostic,answered:2,status:"uncertain"},feedback:feedback("recorded",q)};
    else if(q.probe_id==="r1")episode={...episode,question:q3,feedback:feedback("correct",q,{answer:"13/42",independent:false})};
    else if(q.probe_id==="r2")episode={...episode,phase:"waiting",question:null,due_at:"2026-11-12T06:00:00Z",
     evidence:{...episode.evidence,independent_practice:1},feedback:feedback("correct",q,{answer:"5/7",independent:true})};
    else if(q.probe_id==="r3")episode={...episode,phase:"transfer",question:{...q5,prompt_zh:"求 x 的值。",prompt_en:"Find x."},
     evidence:{...episode.evidence,delayed_review:1},feedback:feedback("correct",q,{answer:"5/8",independent:true})};
    else episode={...episode,phase:"waiting",question:null,due_at:"2026-11-15T06:00:00Z",review_round:1,
     evidence:{...episode.evidence,structural_transfer:1},feedback:feedback("correct",q,{answer:"-1/42",independent:true})};
    receipts.set(data.request_id,structuredClone(episode));
    if(action==="answer"&&loseResponse){loseResponse=false;return route.abort("failed");}
   }
  }
  body=envelope();
 }
 await route.fulfill({json:body});
});
await page.routeWebSocket("**/api/**",()=>{});
const base=process.env.LOOP_QA_URL||"http://127.0.0.1:3199";
const panel=page.locator('section[aria-labelledby="learning-loop-title"]');
const chooseEnglish=()=>page.evaluate(()=>{localStorage.setItem("mathtutor-language","en");window.dispatchEvent(new Event("mathtutor-language-change"));});
const fillSubmit=async answer=>{await panel.getByRole("textbox",{name:"Enter your numerical answer"}).fill(answer);await panel.getByRole("button",{name:"Submit answer",exact:true}).click();};
try{
 await page.setViewportSize({width:375,height:812});
 await page.goto(base+"/math-tutor/profile");
 await panel.getByRole("button",{name:"开始检查",exact:true}).click();
 await panel.getByRole("textbox",{name:"填写数值答案"}).fill("2/3");
 await panel.getByRole("button",{name:"有符号减法",exact:true}).click();
 await panel.getByRole("button",{name:"分数加法",exact:true}).click();
 assert.equal(await panel.getByRole("textbox",{name:"填写数值答案"}).inputValue(),"2/3");
 await chooseEnglish();
 assert.equal(await panel.getByRole("textbox",{name:"Enter your numerical answer"}).inputValue(),"2/3");
 await panel.getByRole("button",{name:"Submit answer",exact:true}).click();
 await panel.getByRole("alert").waitFor();
 assert.equal(await panel.getByRole("textbox").inputValue(),"2/3");
 await panel.getByRole("button",{name:"Submit answer",exact:true}).click();
 await panel.getByText(q2.statement,{exact:true}).waitFor();
 assert.equal(answerIds[0],answerIds[1],"lost-response retry retains request identity");
 assert.equal(await panel.getByRole("textbox").inputValue(),"");
 await fillSubmit("?");
 await panel.getByText("Enter an integer, decimal, or fraction so the answer can be checked.",{exact:true}).waitFor();
 assert.equal(await panel.getByRole("textbox").getAttribute("aria-invalid"),"true");
 await panel.getByRole("button",{name:"View solution (assisted practice)",exact:true}).click();
 await panel.getByText("Answer: 13/42",{exact:true}).waitFor();
 await fillSubmit("13/42");
 await panel.getByText(q3.statement,{exact:true}).waitFor();
 await panel.getByText("Your correct answer after viewing the solution is saved. Try a fresh problem independently.",{exact:true}).waitFor();
 assert.match(await panel.innerText(),/Independent practice\s*0/);
 await fillSubmit("5/7");
 await panel.getByText("Waiting for spaced review",{exact:true}).waitFor();
 assert.equal(await panel.getByRole("button",{name:"Start review",exact:true}).count(),0);
 assert.match(await panel.innerText(),/Delayed review\s*0/);
 due=true;
 await panel.getByRole("button",{name:"Sync progress",exact:true}).click();
 await panel.getByRole("button",{name:"Start review",exact:true}).click();
 await panel.getByText(q4.statement,{exact:true}).waitFor();
 await fillSubmit("5/8");
 await panel.getByText(q5.statement,{exact:true}).waitFor();
 await fillSubmit("-1/42");
 await panel.getByText("Waiting for spaced review",{exact:true}).waitFor();
 await page.reload();
 await panel.getByText("Waiting for spaced review",{exact:true}).waitFor();
 assert.match(await panel.innerText(),/Delayed review\s*1/);
 assert.match(await panel.innerText(),/Changed-structure practice\s*1/);
 for(const theme of ["light","dark"]){
  await page.emulateMedia({colorScheme:theme,reducedMotion:"reduce"});
  for(const [width,height] of [[1280,900],[375,812],[812,375]]){
   await page.setViewportSize({width,height});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   const button=panel.getByRole("button",{name:"Adding fractions",exact:true});await button.focus();
   const box=await button.boundingBox();assert.ok(box.height>=44&&box.width>=44);
   assert.notEqual(await button.evaluate(el=>getComputedStyle(el).outlineStyle),"none");
   assert.ok(!/[\u3400-\u9fff]/u.test(await panel.innerText()),"English UI contains no untranslated fixed copy");
   await panel.getByRole("heading",{name:"Concept check",exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(output,`loop-${theme}-${width}.png`),animations:"disabled"});
   const lastRecord=panel.getByText("Changed-structure practice",{exact:true});
   await lastRecord.scrollIntoViewIfNeeded();
   const recordBox=await lastRecord.boundingBox();
   assert.ok(recordBox.y>=0 && recordBox.y+recordBox.height<=height,"record is reachable in the page scroll area");
   await page.screenshot({path:path.join(output,`loop-records-${theme}-${width}.png`),animations:"disabled"});
  }
 }
 assert.deepEqual(errors,[]);
 const report={status:"PASS",scope:"synthetic browser API fixtures; no student data or learning-effect claims",checks:[
  "language and domain switches preserve draft","lost response retries same id","unknown answer stays ungraded","helped answer not independent",
  "feedback belongs to previous question","server-gated due review","review to structural transfer","reload preserves state",
  "three viewports light/dark reduced-motion","visible keyboard focus and >=44px targets","record counts reachable by scrolling"],screenshots:12,errors,output};
 await writeFile(path.join(output,"browser-verification.json"),JSON.stringify(report,null,2)+"\n");
 console.log(JSON.stringify(report));
}finally{await browser.close();}

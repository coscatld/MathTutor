// Actual settings UI with delayed synthetic API receipts. Never calls a model.
import assert from "node:assert/strict";
import {mkdtemp, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE,args:["--no-proxy-server"]});
const context=await browser.newContext({viewport:{width:1280,height:1000},reducedMotion:"reduce"});
const base=process.env.LAYOUT_URL || "http://127.0.0.1:3198";
const output=await mkdtemp(path.join(tmpdir(),"mathtutor-settings-contract-"));
const checks=[],errors=[],writes=[];
let revision=1, pendingProbe=null, pendingSave=null, pendingSkip=null;
const epoch="synthetic-settings-runtime";
let config={preset_id:"custom",model:"fixture-model-a",base_url:"https://fixture.invalid/v1",vision_mode:"auto",is_configured:true,onboarding_completed:true,key_masked:"••••1234",provider_configs:{},epoch,revision,current_revision:revision,persisted:true,persistence_error:null};
const pass=name=>{checks.push(name);console.log("PASS "+name);};
async function waitPending(read){
 const deadline=Date.now()+15000;
 while(!read()){assert.ok(Date.now()<deadline,"request did not reach controlled API barrier");await new Promise(r=>setTimeout(r,10));}
 return read();
}
await context.route("**/api/**",async route=>{
 const req=route.request(),p=new URL(req.url()).pathname;
 let json=[];
 if(p.endsWith("/auth/status"))json={enabled:false,authenticated:true};
 else if(p.endsWith("/bootstrap"))json={phase:"READY",readiness:"READY",steps:[]};
 else if(p.endsWith("/settings/presets"))json=[{preset_id:"custom",label:"自定义 (OpenAI 兼容)",custom:true,editable_base_url:true,base_url:"",default_model:""}];
 else if(p.endsWith("/settings/embedding"))json={enabled:false,provider:"local",local_model_id:"fixture",local_models:[],status:"disabled"};
 else if(p.endsWith("/model/test")){
  const input=req.postDataJSON();writes.push({kind:"probe",input});pendingProbe={route,input};return;
 }else if(p.endsWith("/settings") && req.method()==="PUT"){
  const input=req.postDataJSON();writes.push({kind:"save",input});pendingSave={route,input};return;
 }else if(p.endsWith("/settings/onboarding/skip")){
  const input=req.postDataJSON();writes.push({kind:"skip",input});pendingSkip={route,input};return;
 }else if(p.endsWith("/settings"))json=config;
 await route.fulfill({json});
});
context.on("page",page=>page.on("pageerror",e=>errors.push(e.message)));
try{
 const page=await context.newPage();page.setDefaultTimeout(15000);
 await page.goto(base+"/math-tutor/settings");
 await page.locator("#settings-apikey").waitFor();
 await page.getByRole("button",{name:"自定义模型",exact:true}).click();
 const model=page.locator("#settings-model"),save=page.getByRole("button",{name:"保存设置",exact:true}),test=page.getByRole("button",{name:"测试连接",exact:true});
 await test.click();let request=await waitPending(()=>pendingProbe);
 assert.equal(request.input.revision,revision);assert.equal(request.input.epoch,epoch);assert.ok(request.input.operation_id);
 assert.ok(await save.isDisabled());
 await model.fill("用户在探测期间编辑的新模型");
 await request.route.fulfill({json:{ok:true,error_kind:null,message:"fixture probe",resolved_model:"old-probe-result",epoch,revision,current_revision:revision,operation_id:request.input.operation_id,provider_id:"custom",accepted:true,persisted:true,persistence_error:null}});pendingProbe=null;
 await test.waitFor({state:"visible"});await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 assert.equal(await model.inputValue(),"用户在探测期间编辑的新模型");
 assert.equal(await page.getByText("连接成功，模型可正常调用",{exact:true}).count(),0);
 pass("test and save are mutually exclusive; a completed probe cannot replace a newer model draft or display stale success");

 await model.fill("submitted-model-b");await save.click();request=await waitPending(()=>pendingSave);
 assert.equal(request.input.expected_revision,revision);assert.equal(request.input.expected_epoch,epoch);assert.ok(request.input.operation_id);assert.equal(request.input.model,"submitted-model-b");
 assert.ok(await test.isDisabled());await model.fill("later-unsaved-model-c");
 revision+=1;config={...config,model:request.input.model,revision,current_revision:revision,persisted:false,persistence_error:"config_write_failed"};
 await request.route.fulfill({json:{...config,accepted:true,operation_id:request.input.operation_id}});pendingSave=null;
 await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 assert.equal(await model.inputValue(),"later-unsaved-model-c");
 const failureNotice=page.getByRole("status").filter({hasText:/本次运行|磁盘|持久/});await failureNotice.first().waitFor();
 assert.equal(await page.getByText("模型设置已保存",{exact:true}).count(),0);
 pass("runtime-only save receipt reports persistence failure and preserves edits made after submission");

 await save.click();request=await waitPending(()=>pendingSave);
 assert.equal(request.input.expected_revision,revision);assert.equal(request.input.model,"later-unsaved-model-c");
 revision+=1;config={...config,model:request.input.model,revision,current_revision:revision,persisted:true,persistence_error:null};
 await request.route.fulfill({json:{...config,accepted:true,operation_id:request.input.operation_id}});pendingSave=null;
 await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 assert.equal(await model.inputValue(),"later-unsaved-model-c");
 await page.getByRole("form",{name:"AI 模型设置",exact:true}).getByText("自定义模型已保存并生效。",{exact:true}).waitFor();
 pass("retry sends the updated configuration revision and confirms durable save only after a successful receipt");

 await page.getByRole("button",{name:"通用",exact:true}).click();
 await page.getByRole("combobox",{name:"界面语言",exact:true}).selectOption("en");
 await page.getByRole("button",{name:"Models & API",exact:true}).click();
 const englishSave=page.getByRole("button",{name:"Save settings",exact:true}),englishTest=page.getByRole("button",{name:"Test connection",exact:true});
 await englishSave.click();request=await waitPending(()=>pendingSave);
 revision+=1;config={...config,revision,current_revision:revision,persisted:false,persistence_error:"config_write_failed"};
 await request.route.fulfill({json:{...config,accepted:true,operation_id:request.input.operation_id}});pendingSave=null;
 await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 await page.getByRole("status").filter({hasText:/session|disk|saved|persist/i}).first().waitFor();
 await englishTest.click();request=await waitPending(()=>pendingProbe);
 await request.route.fulfill({json:{ok:false,error_kind:null,message:"配置已变化，请重新测试当前配置。",resolved_model:"foreign-result",epoch,revision,current_revision:revision+1,operation_id:request.input.operation_id,provider_id:"custom",accepted:false,persisted:false,persistence_error:null}});pendingProbe=null;
 await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 assert.equal(await page.getByText("Connection successful. The model is ready to use",{exact:true}).count(),0);
 assert.equal(await model.inputValue(),"later-unsaved-model-c");
 await page.setViewportSize({width:375,height:900});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.getByRole("form",{name:"AI model settings",exact:true}).getByRole("status").scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(output,"settings-runtime-only-english-mobile.png"),fullPage:false});
 pass("English feedback handles runtime-only persistence and rejects a result from a newer external revision at 375px");

 await page.setViewportSize({width:1280,height:1000});
 await page.goto(base+"/onboarding/provider");
 const key=page.locator("#onboarding-api-key");await key.waitFor();
 assert.equal(new URL(page.url()).pathname,"/onboarding/provider","runtime-only config must not skip onboarding after reload");
 await key.fill("sk-synthetic-first-draft");
 const continueButton=page.getByRole("button",{name:"Save and continue",exact:true});
 const skipButton=page.getByRole("button",{name:"Skip for now and use template tutoring",exact:true});
 await continueButton.click();request=await waitPending(()=>pendingSave);
 assert.ok(await skipButton.isDisabled());await key.fill("sk-synthetic-newer-draft");
 revision+=1;config={...config,revision,current_revision:revision,persisted:false,persistence_error:"config_write_failed"};
 await request.route.fulfill({json:{...config,accepted:true,operation_id:request.input.operation_id}});pendingSave=null;
 await continueButton.waitFor();await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 assert.equal(new URL(page.url()).pathname,"/onboarding/provider");
 assert.equal(await key.inputValue(),"sk-synthetic-newer-draft");
 await page.getByText("Active for this session, but not saved to disk. Retry saving; restarting may restore the previous configuration.",{exact:true}).waitFor();
 pass("onboarding reload and save retain the form and newer API-key draft when persistence fails");

 await skipButton.click();request=await waitPending(()=>pendingSkip);
 assert.equal(request.input.revision,revision);assert.equal(request.input.epoch,epoch);
 assert.ok(await continueButton.isDisabled());
 revision+=1;config={...config,revision,current_revision:revision};
 await request.route.fulfill({json:{...config,ok:true,accepted:true,operation_id:request.input.operation_id}});pendingSkip=null;
 await skipButton.waitFor();await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 assert.equal(new URL(page.url()).pathname,"/onboarding/provider");
 assert.equal(await key.inputValue(),"sk-synthetic-newer-draft");
 assert.equal(await page.evaluate(()=>JSON.stringify(localStorage).includes("sk-synthetic")),false);
 pass("onboarding skip uses the current revision and cannot navigate away on a runtime-only persistence receipt");
 assert.deepEqual(errors,[]);
 assert.equal(await page.evaluate(()=>JSON.stringify(localStorage).includes("fixture-model")),false);
 await writeFile(path.join(output,"results.json"),JSON.stringify({status:"PASS",checks,errors,requestCount:writes.length,scope:"Actual macOS Chromium; controlled synthetic REST receipts; no model calls."},null,2));
 console.log("Evidence: "+output);
}catch(error){
 const page=context.pages()[0];if(page)await page.screenshot({path:path.join(output,"failure.png"),fullPage:true});
 console.error("Evidence: "+output);throw error;
}finally{await browser.close();}

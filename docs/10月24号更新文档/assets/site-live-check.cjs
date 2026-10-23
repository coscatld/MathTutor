/** Read-only live acceptance. Run only after the parent confirms deployment. */
const {chromium}=require(process.env.MATHTUTOR_PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
if(process.env.MATHTUTOR_SITE_DEPLOYED !== 'yes') throw new Error('Await explicit deployment confirmation before any network access.');
const deploymentCommit=process.env.MATHTUTOR_DEPLOYMENT_COMMIT;
if(!deploymentCommit) throw new Error('MATHTUTOR_DEPLOYMENT_COMMIT is required to identify the deployed source.');
const base='https://coscatld.github.io/MathTutor';
const dir=__dirname;
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce',colorScheme:'light'});
 const page=await context.newPage();page.setDefaultTimeout(15000);page.setDefaultNavigationTimeout(45000);
 const checks=[],pageErrors=[],resourceErrors=[],networkFailures=[];
 const result={at:new Date().toISOString(),commit:deploymentCommit,base,browser:'installed Chrome, new isolated context; no user account',data:'published static site; no API mocks',checks,pageErrors,resourceErrors,networkFailures};
 page.on('pageerror',e=>pageErrors.push(e.message));
 page.on('response',response=>{if(response.url().startsWith(base+'/') && response.status()>=400)resourceErrors.push({url:response.url(),status:response.status(),type:response.request().resourceType()});});
 page.on('requestfailed',request=>{const error=request.failure()?.errorText;if(error&&!error.includes('ERR_ABORTED'))networkFailures.push({url:request.url(),error});});
 async function visit(route,title,content){
  const response=await page.goto(base+route,{waitUntil:'networkidle'});
  assert.equal(response.status(),200,route);
  assert.equal(await page.locator('h1').count(),1,route+' H1 count');
  assert.equal((await page.locator('h1').innerText()).trim(),title,route+' deployed title');
  if(content)assert.ok((await page.locator('body').innerText()).includes(content),route+' deployed content');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),route+' horizontal bounds');
  checks.push({route,status:response.status(),title,viewport:page.viewportSize(),overflow:false});
 }
 try{
  await visit('/zh/','让每一步推理，都有迹可循。','从自己尝试一道题开始');
  await visit('/zh/docs/','把 MathTutor 用起来','先分清三个地方');
  await visit('/zh/docs/user/knowledge-base/','知识库与参考资料','向这些位置加入可检索资料，可能改变有效范围');
  await visit('/zh/docs/user/learning-evidence/','学习画像与证据','排除首次判定不会让同题重做变成首次作答');
  await visit('/en/docs/','Make MathTutor yours','Three places, three purposes');
  await page.goto(base+'/zh/',{waitUntil:'networkidle'});
  await page.getByRole('navigation',{name:'按目标阅读'}).getByRole('link').first().click();
  await page.waitForURL(url=>url.pathname==='/MathTutor/zh/docs/user/quick-start/');
  checks.push('home task entry opens quick-start');
  await page.goto(base+'/zh/docs/',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'Choose a language'}).click();
  await page.locator('a[href="/MathTutor/en/docs/"]').last().click();
  await page.waitForURL(url=>url.pathname==='/MathTutor/en/docs/');
  checks.push('language switch preserves docs path');
  await page.goto(base+'/zh/docs/',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'搜索文档'}).click();
  await page.getByRole('combobox').fill('学习画像');
  const searchResult=page.getByRole('option').filter({hasText:'学习画像与证据'}).first();
  await searchResult.waitFor({state:'visible'});
  await searchResult.click();
  await page.waitForURL(url=>url.pathname==='/MathTutor/zh/docs/user/learning-evidence/');
  checks.push('live static search returns a real evidence result and navigates to it');
  await page.getByRole('button',{name:'搜索文档'}).click();
  await page.getByRole('dialog').waitFor();await page.keyboard.press('Escape');
  await page.getByRole('dialog').waitFor({state:'hidden'});
  checks.push('Escape closes the search dialog');
  for(const language of ['zh','en']){
   await page.goto(base+'/'+language+'/docs/user/faq/',{waitUntil:'networkidle'});
   const link=page.locator('a[href="../installation"]').first();
   await link.click();await page.waitForURL(url=>url.pathname===`/MathTutor/${language}/docs/user/installation/`);
   for(const [href,destination] of [['../quick-start','user/quick-start/'],['../../developer/development-setup','developer/development-setup/']]){
    const target=await page.locator(`a[href="${href}"]`).first().getAttribute('href');
    const response=await context.request.get(new URL(target,page.url()).href);
    assert.equal(response.status(),200,language+' '+href);
    checks.push(language+' installation link resolves '+destination);
   }
  }
  await page.goto(base+'/zh/docs/',{waitUntil:'networkidle'});
  await page.screenshot({path:path.join(dir,'site-live-docs-desktop.png'),fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await visit('/zh/','让每一步推理，都有迹可循。');
  await visit('/zh/docs/','把 MathTutor 用起来');
  await visit('/zh/docs/user/knowledge-base/','知识库与参考资料');
  await visit('/zh/docs/user/learning-evidence/','学习画像与证据');
  await page.goto(base+'/zh/docs/',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'Open Sidebar',exact:true}).click();
  await page.getByRole('link',{name:'学习画像与证据',exact:true}).click();
  await page.waitForURL(url=>url.pathname==='/MathTutor/zh/docs/user/learning-evidence/');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  checks.push('mobile sidebar exposes evidence guide, navigates and has no horizontal overflow');
  await page.screenshot({path:path.join(dir,'site-live-evidence-mobile.png'),fullPage:true,animations:'disabled'});
  assert.deepEqual(pageErrors,[],'browser runtime errors');assert.deepEqual(resourceErrors,[],'HTTP resource errors');assert.deepEqual(networkFailures,[],'network failures');
  result.status='PASS';
 } catch(error){result.status='FAIL';result.failure=error.stack||String(error);throw error;}
 finally{fs.writeFileSync(path.join(dir,'site-live-results.json'),JSON.stringify(result,null,2)+'\n');await browser.close();console.log(JSON.stringify(result,null,2));}
})().catch(error=>{console.error(error);process.exitCode=1;});

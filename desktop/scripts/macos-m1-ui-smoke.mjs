// Runs the copied DMG application, with a generated profile and isolated cache.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const {_electron} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [appRoot, dataRoot, evidenceDir] = process.argv.slice(2);
assert.ok(appRoot && dataRoot && evidenceDir);
fs.mkdirSync(evidenceDir, {recursive:true});
const env = Object.fromEntries(['PATH','HOME','TMPDIR','LANG'].filter(k=>process.env[k]).map(k=>[k,process.env[k]]));
const application = await _electron.launch({
  executablePath:path.join(appRoot,'Contents/MacOS/MathTutor'),
  args:[`--user-data-dir=${path.join(dataRoot,'chromium')}`],
  env:{...env,MATHTUTOR_DATA_ROOT:dataRoot,PYTHONDONTWRITEBYTECODE:'1'},
  cwd:path.dirname(dataRoot),timeout:90000,
});
let page;
try {
  page = await application.firstWindow({timeout:90000});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.waitForURL(/127\.0\.0\.1/, {timeout:90000});
  const base = new URL(page.url()).origin;
  await page.goto(base+'/math-tutor/profile');
  const skip = page.getByRole('button',{name:'暂时跳过，使用模板教学',exact:true});
  await page.getByRole('heading',{name:'学习画像',exact:true}).or(skip).waitFor();
  if (await skip.isVisible()) {
    await skip.click();
    await page.waitForURL(/\/math-tutor/);
    await page.goto(base+'/math-tutor/profile');
  }
  await page.getByRole('heading',{name:'学习画像',exact:true}).waitFor();
  await page.getByRole('button',{name:'查看依据',exact:true}).first().click();
  await page.getByRole('dialog').waitFor();
  await page.getByText('2x + 3 = 7', {exact:false}).first().waitFor();
  await page.screenshot({path:path.join(evidenceDir,'upgraded-profile-evidence.png')});
  await page.keyboard.press('Escape');
  await page.goto(base+'/math-tutor/offers');
  await page.getByRole('button',{name:'继续练习',exact:true}).waitFor();
  await page.screenshot({path:path.join(evidenceDir,'upgraded-continue-practice.png')});
  await page.getByRole('button',{name:'继续练习',exact:true}).click();
  await page.waitForURL(/session=rc-upgrade-session/);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'PASS',packaged_electron:true,api_mocked:false,
    profile_evidence_drawer:true,continue_practice_navigation:true,page_errors:errors,
    screenshots:['upgraded-profile-evidence.png','upgraded-continue-practice.png']}));
} catch (error) {
  if (page) {
    await page.screenshot({path:path.join(evidenceDir,'failure.png')});
    console.error(JSON.stringify({url:page.url(),body:(await page.locator('body').innerText()).slice(0,2500)}));
  }
  throw error;
} finally {await application.close();}

// Isolated browser QA: all backend requests use non-personal fixtures.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = await mkdtemp(path.join(tmpdir(), 'mathtutor-profile-'));
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_EXECUTABLE});
const page = await browser.newPage();
const errors=[];
page.on('pageerror', error=>errors.push(error.message));
let excluded=false, empty=false;
const skill={code:'linear_isolation',label:'移项与符号处理',mastery:null,grade_band:null,observation:'有 2 道新题首次独立完成，仍可换题检查。',evidence_count:2,counts:{independent:{correct:2,incorrect:0},assisted:{correct:1,incorrect:0},post_solution:{correct:0,incorrect:0},diagnostic:{correct:0,incorrect:0}},last_checked_at:'2026-09-13T08:00:00Z'};
const offer={offer_id:'practice-1',status:'ACTIVE',display_status:'pending',skill_labels:['移项与符号处理'],concept_labels:[],difficulty:2,offered_at:'2026-09-13T08:00:00Z',expires_at:'2026-09-15T08:00:00Z',parent_cycle_id:'parent',title:'换一道题，检查独立完成情况',reason:'上一次作答中使用过提示。',observation_goal:'不看例题时，能否正确处理符号。',question_count:1};
await page.route('**/api/**', async route=>{
  const url=new URL(route.request().url());
  let body=[];
  if(url.pathname.endsWith('/auth/status'))body={enabled:false,authenticated:true};
  else if(url.pathname.endsWith('/bootstrap'))body={phase:'READY',readiness:'READY',steps:[]};
  else if(url.pathname.endsWith('/sessions'))body=[{conversation_id:'s',title:'一次数学问答'}];
  else if(url.pathname.endsWith('/settings'))body={is_configured:true,onboarding_completed:true,preset_id:'deepseek',model:'fixture',base_url:'',key_masked:null};
  else if(url.pathname.endsWith('/presets'))body=[{preset_id:'deepseek',label:'DeepSeek',default_model:'fixture',base_url:'',editable_base_url:true}];
  else if(url.pathname.endsWith('/student-summary'))body={skills:[empty?{...skill,evidence_count:0,observation:'尚未检查'}:skill],total_attempts:empty?0:2,active_misconceptions:0,has_conversations:true,has_independent_evidence:!empty,coverage:{supported_skills:13,observed_skills:empty?0:1}};
  else if(url.pathname.endsWith('/student-evidence'))body={items:[{event_id:'event-1',event_seq:1,cycle_id:'cycle',occurred_at:'2026-09-13T08:00:00Z',skill_ids:['linear_isolation'],problem_text:'解方程：3x − 5 = 10',student_response:'x = 5',correctness:'correct',evidence_kind:'independent',completion_scope:'full_problem',first_target:!excluded,excluded,session_id:'s'}],next_cursor:null};
  else if(url.pathname.endsWith('/exclude')){excluded=true;body={ok:true};}
  else if(url.pathname.endsWith('/recompute-profile'))body={ok:true};
  else if(url.pathname.endsWith('/offers'))body=[offer,{...offer,offer_id:'ongoing',status:'ACCEPTED',display_status:'in_progress',resume_session_id:'s',title:'继续检查移项时的符号'}, {...offer,offer_id:'done',status:'ACCEPTED',display_status:'completed',title:'刚完成的练习',result_summary:{independent_correct:1,helped:0,observations:1},evidence_href:'/math-tutor/profile?cycle=cycle'}];
  else if(url.pathname.endsWith('/resume'))body={session_id:'s'};
  else if(url.pathname.includes('embedding'))body={enabled:false,status:'disabled',provider:'local',local_models:[]};
  await route.fulfill({json:body});
});
const base=process.env.PROFILE_QA_URL || 'http://127.0.0.1:3198';
try{
  for(const [width,height] of [[1280,800],[1024,768],[375,812],[812,375]]){
    await page.setViewportSize({width,height});
    await page.goto(base+'/math-tutor/profile');
    await page.getByRole('heading',{name:skill.observation,exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth),false);
    await page.screenshot({path:path.join(output,`profile-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'查看依据',exact:true}).click();
    await page.getByRole('dialog').waitFor();
    const bounds=await page.getByRole('dialog').boundingBox();
    assert.ok(bounds.x>=0 && bounds.x+bounds.width<=width+1);
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state:'detached'});
    assert.equal(await page.getByRole('button',{name:'查看依据',exact:true}).evaluate(el=>el===document.activeElement),true);
  }
  await page.setViewportSize({width:1280,height:800});
  await page.goto(base+'/math-tutor/offers');
  await page.getByRole('button',{name:'继续练习',exact:true}).waitFor();
  assert.ok((await page.getByRole('heading',{name:'先继续这道题'}).boundingBox()).y < (await page.getByRole('heading',{name:'接下来可选'}).boundingBox()).y);
  await page.screenshot({path:path.join(output,'offers.png'),fullPage:true});
  await page.getByRole('link',{name:'查看学习记录'}).click();
  await page.getByRole('dialog',{name:'本次学习记录'}).waitFor();
  await page.getByRole('button',{name:'这条记录有问题'}).click();
  await page.getByRole('button',{name:'排除这次判定'}).click();
  await page.getByText('已排除判定',{exact:true}).waitFor();
  await page.keyboard.press('Escape');
  empty=true;
  await page.goto(base+'/math-tutor/profile');
  await page.getByRole('heading',{name:'已有问答，独立作答还待观察'}).waitFor();
  await page.screenshot({path:path.join(output,'profile-chat-only.png'),fullPage:true});
  await page.goto(base+'/math-tutor/settings');
  await page.getByRole('button',{name:'数据与隐私',exact:true}).click();
  await page.getByRole('button',{name:'重新计算学习画像',exact:true}).waitFor();
  assert.equal(await page.getByRole('dialog').count(),0);
  await page.getByRole('button',{name:'重新计算学习画像',exact:true}).click();
  await page.getByText('已根据有效记录重新计算学习画像。',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',viewportCount:4,output}));
}finally{await browser.close();}

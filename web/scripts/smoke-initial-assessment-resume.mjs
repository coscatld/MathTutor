// Actual React/Next interactions with durable, explicitly synthetic API fixtures.
// API ownership, transactions and SQLite restart are separately checked in pytest.
import assert from 'node:assert/strict';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = await mkdtemp(path.join(tmpdir(), 'mathtutor-1028-assessment-'));
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
let page = await context.newPage();
const errors = [], checks = [], mutations = [];
context.on('page', p => p.on('pageerror', error => errors.push(error.message)));
page.on('pageerror', error => errors.push(error.message));
const prefix = '/api/v2/math-tutor/desktop/initial-assessment';
const version = 'synthetic-unchanged-item-set';
let saved = { run_id: 'synthetic-run-a', status: 'pending', answers: [], assessment_version: version };
let resumeFailure = false, resumeGate, releaseResume, resumeCalls = 0, readGate, releaseRead, readCalls = 0;
const publicState = () => {
  const index = saved.answers.length;
  return { run_id: saved.run_id, status: saved.status, total: 10, answered: index,
    assessment_version: saved.assessment_version,
    can_resume: saved.status === 'skipped' && saved.assessment_version === version,
    compatibility_notice: saved.assessment_version === version ? null : '这份初评的题目或规则版本已更新，暂不能续做。已有作答保留，可继续学习。',
    question: ['pending', 'in_progress'].includes(saved.status) && saved.assessment_version === version && index < 10 ? {
      index, skill_label: '合成初评题', statement: `第 ${index + 1} 道合成题：1 + ${index + 1}`,
      choices: { format: 'single_choice', version: `synthetic-q-${index}`, options: ['A', 'B', 'C', 'D'].map((id, i) => ({ id, text: String(i + 1) })) },
    } : null,
    result: saved.status === 'completed' ? { notice: '合成初评结果，仅用于交互回归。', skills: [] } : null,
  };
};
const scope = { space_ids: [], document_ids: [], only_selected: false, mode: 'tutor', hints_only: false, save_space_id: '', tool_mode: 'native', available_documents: [], effective_document_ids: [] };
await context.route('**/api/**', async route => {
  const request = route.request(), p = new URL(request.url()).pathname;
  const reply = (json, status = 200) => route.fulfill({ status, json });
  if (request.method() !== 'GET') mutations.push(p);
  if (p === prefix) {
    readCalls++;
    const snapshot = publicState();
    if (readGate) await readGate;
    return reply(snapshot);
  }
  if (p.startsWith(prefix + '/')) {
    const action = p.slice(prefix.length + 1), body = request.postDataJSON();
    if (action === 'start') return reply(publicState());
    if (body.run_id !== saved.run_id) return reply({ detail: '初评不属于当前学生' }, 409);
    if (action === 'skip') { if (saved.status !== 'completed') saved.status = 'skipped'; return reply({ ok: true }); }
    if (action === 'resume') {
      resumeCalls++;
      if (resumeFailure) return reply({ detail: '暂时不能恢复，请重试。' }, 503);
      if (resumeGate) await resumeGate;
      if (body.version !== version || saved.assessment_version !== version) return reply({ detail: '版本不兼容，已有作答保留。' }, 409);
      if (saved.status === 'skipped') saved.status = saved.answers.length ? 'in_progress' : 'pending';
      return reply(publicState());
    }
    if (action === 'answer') {
      if (!['pending', 'in_progress'].includes(saved.status) || body.index !== saved.answers.length) return reply({ detail: '首次选择不能覆盖' }, 409);
      saved.answers.push(body);
      saved.status = saved.answers.length === 10 ? 'completed' : 'in_progress';
      return reply(publicState());
    }
  }
  if (p.endsWith('/auth/status')) return reply({ enabled: false, authenticated: true });
  if (p.endsWith('/bootstrap')) return reply({ phase: 'READY', readiness: 'READY', steps: [] });
  if (p.endsWith('/settings')) return reply({ is_configured: true, onboarding_completed: true, initial_assessment_required: ['pending', 'in_progress'].includes(saved.status), preset_id: 'deepseek', model: 'fixture', base_url: '', key_masked: null });
  if (p.endsWith('/presets')) return reply([{ preset_id: 'deepseek', label: 'DeepSeek', default_model: 'fixture', base_url: '', editable_base_url: true }]);
  if (p.endsWith('/sessions')) return reply([]);
  if (p.includes('/sessions/')) return reply({ messages: [], state: 'idle', state_version: 0 });
  if (p.endsWith('/student-summary')) return reply({ skills: [], total_attempts: 1, active_misconceptions: 0, has_conversations: true, has_independent_evidence: false, coverage: { supported_skills: 5, observed_skills: 0 } });
  if (p.endsWith('/stage-review')) return reply({ status: 'idle', preferences: {}, review: null });
  if (p.includes('/knowledge/conversations/')) return reply(scope);
  if (p.endsWith('/resources')) return reply({ documents: [], images: [], message_count: 0, scope });
  if (p.includes('embedding')) return reply({ enabled: false, status: 'disabled', provider: 'local', local_models: [] });
  return reply([]);
});
await context.routeWebSocket('**/api/**', () => {});
const base = process.env.LAYOUT_URL || 'http://127.0.0.1:3198';
const pass = value => { checks.push(value); console.log('PASS ' + value); };
async function chooseUnsure() {
  const next = saved.answers.length + 1;
  await page.getByRole('heading', { name: `第 ${next} 道合成题：1 + ${next}`, exact: true }).waitFor();
  await page.getByRole('radio', { name: /暂时不确定/ }).check();
  await page.getByRole('button', { name: '提交选择', exact: true }).click();
}
try {
  await page.goto(base + '/onboarding/assessment');
  for (let i = 0; i < 3; i++) await chooseUnsure();
  await page.getByRole('heading', { name: '第 4 道合成题：1 + 4', exact: true }).waitFor();
  const firstThree = structuredClone(saved.answers);
  await page.getByRole('button', { name: '暂缓初评，先开始学习', exact: true }).click();
  await page.waitForURL('**/math-tutor');
  assert.equal(saved.status, 'skipped');
  await page.close();
  page = await context.newPage();
  await page.goto(base + '/');
  await page.waitForURL('**/math-tutor');
  assert.equal(resumeCalls, 0, 'starting the app does not automatically resume');
  pass('three answers survive deferral and reopening; startup does not force resume');
  await page.goto(base + '/math-tutor/profile');
  await page.getByRole('link', { name: '查看初评与练习起点', exact: true }).click();
  const resume = page.getByRole('button', { name: '继续初评', exact: true });
  await resume.waitFor();
  assert.match(await page.getByRole('region', { name: '暂缓的初评' }).textContent(), /3 \/ 10/);
  assert.equal(await page.getByRole('radio').count(), 0, 'deferred run does not reveal another question');
  await page.setViewportSize({ width: 375, height: 812 });
  assert.ok((await resume.boundingBox()).height >= 44);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(output, 'deferred-mobile.png'), fullPage: true });
  pass('existing learning-profile entry exposes voluntary resume and keeps progress visible');
  resumeFailure = true;
  await resume.click();
  await page.getByRole('alert').filter({ hasText: '暂时不能恢复' }).waitFor();
  assert.equal(saved.status, 'skipped');
  assert.deepEqual(saved.answers, firstThree);
  resumeFailure = false;
  readGate = new Promise(resolve => { releaseRead = resolve; });
  const readsBefore = readCalls;
  await page.getByRole('button', { name: '重新同步进度', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '暂时不能恢复' }).waitFor({ state: 'hidden' });
  assert.equal(readCalls, readsBefore + 1);
  resumeGate = new Promise(resolve => { releaseResume = resolve; });
  const before = resumeCalls;
  await resume.evaluate(button => { button.click(); button.click(); });
  await page.getByRole('button', { name: '正在恢复…', exact: true }).waitFor();
  assert.equal(resumeCalls, before + 1);
  releaseResume(); resumeGate = null;
  await page.getByRole('heading', { name: '第 4 道合成题：1 + 4', exact: true }).waitFor();
  releaseRead(); readGate = null;
  await page.waitForResponse(response => new URL(response.url()).pathname === prefix);
  assert.equal(await page.getByRole('button', { name: '继续初评', exact: true }).count(), 0, 'late pre-resume sync cannot replace the resumed view');
  assert.equal(saved.run_id, 'synthetic-run-a');
  assert.deepEqual(saved.answers, firstThree);
  await page.reload();
  await page.getByRole('heading', { name: '第 4 道合成题：1 + 4', exact: true }).waitFor();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: path.join(output, 'resumed-fourth-question.png'), fullPage: true });
  pass('failed resume retains progress; duplicate clicks send once; late sync cannot reset the resumed view; fourth question survives reload');
  while (saved.answers.length < 10) await chooseUnsure();
  await page.getByRole('region', { name: '初评结果' }).waitFor();
  await page.reload();
  await page.getByRole('region', { name: '初评结果' }).waitFor();
  assert.equal(await page.getByRole('button', { name: '继续初评', exact: true }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '开始初评', exact: true }).count(), 0);
  assert.deepEqual(saved.answers.slice(0, 3), firstThree);
  pass('completion stays completed after reload without retest controls or overwritten first choices');
  saved = { ...saved, status: 'skipped', answers: firstThree, assessment_version: 'incompatible-old-set' };
  await page.goto(base + '/onboarding/assessment');
  await page.getByText(/这份初评的题目或规则版本已更新/).waitFor();
  assert.equal(await page.getByRole('button', { name: '继续初评', exact: true }).count(), 0);
  assert.equal(await page.getByRole('radio').count(), 0);
  assert.equal(await page.getByRole('link', { name: '进入学习', exact: true }).count(), 1);
  assert.deepEqual(saved.answers, firstThree);
  assert.ok(!mutations.some(p => p.includes('/privacy/')));
  assert.deepEqual(errors, []);
  pass('incompatible version explains preservation and keeps learning available; no privacy reset');
  saved = { ...saved, status: 'in_progress' };
  await page.goto(base + '/onboarding/assessment');
  await page.getByText(/这份初评的题目或规则版本已更新/).waitFor();
  assert.equal(await page.getByRole('radio').count(), 0);
  await page.getByRole('button', { name: '暂缓初评，先开始学习', exact: true }).click();
  await page.waitForURL('**/math-tutor');
  await page.reload();
  await page.getByRole('heading', { name: '先用几道小题认识你', exact: true }).waitFor({ state: 'hidden' });
  assert.equal(saved.status, 'skipped');
  assert.deepEqual(saved.answers, firstThree);
  assert.deepEqual(errors, []);
  pass('incompatible active run can defer and enter learning without a startup redirect loop');
  await writeFile(path.join(output, 'results.json'), JSON.stringify({ status: 'PASS', checks, errors, output, scope: 'Actual browser UI with synthetic durable API fixtures; real API/SQLite ownership is separately tested in pytest.' }, null, 2) + '\n');
  console.log(JSON.stringify({ status: 'PASS', checks: checks.length, output }));
} finally { await browser.close(); }

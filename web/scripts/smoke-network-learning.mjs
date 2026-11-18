import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = process.env.NETWORK_QA_OUTPUT;
if (!output) throw new Error('Set NETWORK_QA_OUTPUT to an isolated evidence directory');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const base = process.env.NETWORK_QA_URL || 'http://127.0.0.1:3797';
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], results = [];
page.on('pageerror', error => errors.push(error.message));
const endpoint = '/api/v2/math-tutor/desktop/recommendations';
const screenshot = name => page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
const event = name => page.evaluate(name => window.dispatchEvent(new Event(name)), name);
const visiblePlan = text => page.getByText(text, { exact: true });
try {
  await page.goto(base + '/math-tutor');
  await page.getByRole('textbox', { name: '聊天输入' }).waitFor();
  await page.evaluate(async endpoint => {
    await fetch(endpoint + "/configuration", { method: "PUT", headers: { "X-MathTutor-CSRF": "1", "Content-Type": "application/json" }, body: JSON.stringify({ enabled: false, goal: "math_foundations" }) });
    window.dispatchEvent(new Event("mathtutor-learning-evidence-changed"));
  }, endpoint);
  const initial = await page.evaluate(async endpoint => {
    const response = await fetch(endpoint, { headers: { 'X-MathTutor-CSRF': '1' } });
    if (!response.ok) throw new Error('Recommendation response ' + response.status);
    return response.json();
  }, endpoint);
  assert(initial.plan.resources.length > 0);
  assert.equal(initial.enabled, false);
  assert.equal(initial.plan.evidence_count, 0);
  results.push({ check: 'real_local_catalog_without_online_opt_in', pass: true });
  await screenshot('welcome-desktop');

  let firstRelease, staleRelease, requests = 0, phase = 'initial';
  const firstGate = new Promise(resolve => { firstRelease = resolve; });
  const staleGate = new Promise(resolve => { staleRelease = resolve; });
  await page.route('**/recommendations/start?*', async route => {
    requests++;
    let view = structuredClone(initial);
    if (phase === 'initial') {
      await firstGate;
      view.plan.reason = 'QA owner A';
    } else if (phase === 'stale') {
      await staleGate;
      view.plan.reason = 'QA stale owner A';
    } else {
      view.plan.reason = 'QA owner B';
    }
    await route.fulfill({ json: view }).catch(() => {});
  });
  await page.reload();
  await page.getByRole('textbox', { name: '聊天输入' }).waitFor();
  assert(requests >= 1, "discovery has started while its response remains pending");
  assert.equal(await visiblePlan('QA owner A').count(), 0);
  results.push({ check: 'workbench_ready_before_discovery_response', pass: true, scope: 'browser with delayed recommendation response' });
  firstRelease();
  await visiblePlan('QA owner A').waitFor();

  phase = 'stale';
  await event('mathtutor-learning-evidence-changed');
  await page.waitForTimeout(100);
  assert.equal(await visiblePlan('QA owner A').count(), 0);
  await event('mathtutor-identity-changing');
  const beforeLogout = requests;
  await event('focus');
  await page.waitForTimeout(100);
  assert.equal(requests, beforeLogout);
  phase = 'current';
  await event('mathtutor-identity-changed');
  await visiblePlan('QA owner B').waitFor();
  staleRelease();
  await page.waitForTimeout(100);
  assert.equal(await visiblePlan('QA stale owner A').count(), 0);
  results.push({ check: 'identity_change_clears_and_rejects_late_response', pass: true, scope: 'synthetic owner labels; backend owner isolation separately tested' });

  await event('blur');
  const beforeBlur = requests;
  await event('mathtutor-learning-evidence-changed');
  await page.waitForTimeout(150);
  assert.equal(requests, beforeBlur);
  assert.equal(await visiblePlan('QA owner B').count(), 0);
  await event('focus');
  await visiblePlan('QA owner B').waitFor();
  results.push({ check: 'blur_suspends_evidence_refresh_until_focus', pass: true });

  await page.unroute('**/recommendations/start?*');
  await page.goto(base + '/math-tutor/settings?section=sources');
  await page.getByRole('heading', { name: '为下一步学习找资料' }).waitFor();
  const settings = page.locator('section[aria-labelledby="discovery-settings-title"]');
  await settings.getByRole('combobox').selectOption('probability');
  await page.waitForFunction(() => document.querySelector('section[aria-labelledby="discovery-settings-title"] select')?.value === 'probability');
  await settings.getByRole('checkbox').click();
  await page.waitForFunction(() => document.querySelector('section[aria-labelledby="discovery-settings-title"] input[type=checkbox]')?.checked === true);
  await page.waitForTimeout(400);
  const configured = await page.evaluate(async endpoint => (await fetch(endpoint, { headers: { 'X-MathTutor-CSRF': '1' } })).json(), endpoint);
  assert.equal(configured.goal, 'probability');
  assert.equal(configured.enabled, true);
  results.push({ check: 'real_configuration_goal_and_opt_in', pass: true });
  await settings.getByRole('checkbox').click();
  await page.waitForFunction(() => document.querySelector('section[aria-labelledby="discovery-settings-title"] input[type=checkbox]')?.checked === false);
  await page.waitForTimeout(200);
  await screenshot('sources-settings-desktop');

  for (const [locale, width] of [['zh-CN', 375], ['en', 1440], ['en', 375]]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(locale => { localStorage.setItem('mathtutor-language', locale); window.dispatchEvent(new Event('mathtutor-language-change')); }, locale);
    await page.goto(base + '/math-tutor/profile');
    await page.getByRole('heading', { name: locale === 'en' ? 'Resources for your next step' : '下一步学习资料', exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await page.getByRole('heading', { name: locale === 'en' ? 'Resources for your next step' : '下一步学习资料', exact: true }).scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await screenshot(`profile-${locale}-${width}`);
    results.push({ check: 'profile_responsive_language', locale, width, pass: true });
  }
  await page.evaluate(() => { localStorage.setItem('mathtutor-language', 'zh-CN'); window.dispatchEvent(new Event('mathtutor-language-change')); });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(base + '/math-tutor');
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  const online = page.getByRole('button', { name: '联网', exact: true });
  await online.waitFor();
  assert.equal(await online.getAttribute('aria-pressed'), 'false');
  await online.click();
  assert.equal(await online.getAttribute('aria-pressed'), 'true');
  const input = page.getByRole('textbox', { name: '聊天输入' });
  await input.fill('分数为什么需要通分？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByText('知乎检索或证据检查暂不可用，可以继续用 MathTutor 的已有知识讨论。', { exact: false }).waitFor();
  await screenshot('real-websocket-online-unconfigured');
  results.push({ check: 'real_websocket_online_opt_in_missing_credential_fallback', pass: true, live_provider_calls: 0 });
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('button[aria-pressed]')].some(button => button.textContent === '联网' && button.getAttribute('aria-pressed') === 'false'));
  assert.equal(await online.getAttribute('aria-pressed'), 'false');
  await input.fill('2x+3=7');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByRole('button', { name: '我来写', exact: true }).click({ timeout: 20000 });
  await page.getByRole('button', { name: '提交本题步骤', exact: true }).waitFor();
  assert.equal(await online.isDisabled(), true);
  await screenshot('real-websocket-original-exercise');
  results.push({ check: 'original_math_exercise_preserved_online_disabled_during_attempt', pass: true });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ results, errors }, null, 2));
} finally {
  await writeFile(path.join(output, 'browser-checks.json'), JSON.stringify({ results, errors }, null, 2));
  await browser.close();
}

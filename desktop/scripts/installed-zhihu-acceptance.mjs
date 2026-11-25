import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { setTimeout as pause } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

const { values: args } = parseArgs({ options: {
  executable: { type: 'string' }, output: { type: 'string' },
  'data-root': { type: 'string' }, 'installer-sha256': { type: 'string' },
}});
const data = args['data-root'];
assert(args.executable && args.output && data && args['installer-sha256']);
assert(process.env.MATHTUTOR_ZHIHU_ACCESS_SECRET, 'An authorized Zhihu test credential is required');
fs.mkdirSync(data, { recursive: true });
fs.mkdirSync(args.output, { recursive: true });
assert(!fs.existsSync(path.join(data, 'math_tutor.db')), 'Use an empty test profile');
const report = {
  installer_sha256: args['installer-sha256'], actual_installed_app: false,
  started_at: new Date().toISOString(), cases: {}, automatic_scope: 'failed',
  overall_product_acceptance: 'requires_separate_review',
};
const sha = text => crypto.createHash('sha256').update(text).digest('hex');
const save = () => fs.writeFileSync(path.join(args.output, 'installed-zhihu-acceptance.json'), JSON.stringify(report, null, 2));
const { _electron } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const env = Object.fromEntries(['HOME', 'USERPROFILE', 'USER', 'SystemRoot', 'SYSTEMROOT', 'LOCALAPPDATA', 'APPDATA', 'TMP', 'TEMP', 'TMPDIR', 'LANG', 'MATHTUTOR_ZHIHU_ACCESS_SECRET']
  .filter(key => process.env[key]).map(key => [key, process.env[key]]));
env.PATH = process.platform === 'win32'
  ? path.join(process.env.SystemRoot, 'System32') + ';' + process.env.SystemRoot
  : '/usr/bin:/bin:/usr/sbin:/sbin';
env.MATHTUTOR_DATA_ROOT = data;
env.PYTHONDONTWRITEBYTECODE = '1';
const app = await _electron.launch({
  executablePath: args.executable, args: ['--user-data-dir=' + path.join(data, 'chromium')],
  cwd: os.tmpdir(), env, timeout: 120000,
});

async function waitFor(check, timeout, label) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await pause(150);
  }
  throw new Error('Timed out waiting for ' + label);
}

function readReceipt(turnId) {
  const db = new DatabaseSync(path.join(data, 'math_tutor.db'), { readOnly: true });
  try {
    const row = db.prepare('SELECT content, continuation_context FROM conversation_messages WHERE turn_id=? AND role=?').get(turnId, 'tutor');
    assert(row, 'The completed turn was not saved');
    const receipt = JSON.parse(row.continuation_context).network_evidence;
    assert(receipt && receipt.network_text_sha256 === sha(receipt.network_text));
    assert.equal(row.content, receipt.network_text);
    return receipt;
  } finally {
    db.close();
  }
}

function checkCitations(receipt, visibleLinks, visibleText) {
  const sources = new Map(receipt.sources.map(source => [source.source_id, source]));
  const claims = new Map(receipt.claims.filter(claim => claim.accepted).map(claim => [claim.claim_id, claim]));
  const excerpts = receipt.planner.context_excerpts;
  assert.equal(receipt.planner.context_presentation, 'verbatim_source_excerpts');
  assert(excerpts.length, 'The current answer has no retained source excerpts');
  const citations = [];
  const normalize = text => text.replace(/\s+/g, ' ').trim();
  for (const item of excerpts) {
    const claim = claims.get(item.claim_id);
    assert(claim && receipt.planner.retained_context_ids.includes(item.claim_id));
    assert(claim.evidence.some(e => e.span_id === item.span_id && e.quote_start === item.quote_start && e.quote === item.quote));
    const source = sources.get(item.source_id);
    assert(source?.request_id && source.scope === 'search_excerpt');
    assert.equal(sha(source.raw_excerpt), source.raw_excerpt_sha256);
    const text = [...source.text];
    assert.equal(sha(text.slice(item.span_start, item.span_end).join('')), item.span_sha256);
    assert.equal(text.slice(item.quote_start, item.quote_end).join(''), item.quote);
    assert(normalize(visibleText).includes(normalize(item.quote)), 'The cited passage must be visible in the answer');
    assert(visibleLinks.includes(source.original_url), 'The original link is missing from the answer');
    citations.push({ claim: claim.claim_id, displayed_statement: item.quote,
      source: item.source_id, url: source.original_url, request_id: source.request_id,
      excerpt_sha256: source.raw_excerpt_sha256, start: item.quote_start, end: item.quote_end,
      quote: item.quote, quote_sha256: sha(item.quote) });
  }
  return citations;
}

let page;
try {
  page = await app.firstWindow({ timeout: 120000 });
  page.setDefaultTimeout(20000);
  await page.waitForURL(/http:\/\/127\.0\.0\.1:/, { timeout: 120000 });
  const origin = new URL(page.url()).origin;
  report.identity = { electron: await app.evaluate(({ app }) => ({ packaged: app.isPackaged, version: app.getVersion(), arch: process.arch })) };
  report.actual_installed_app = report.identity.electron.packaged;
  assert(report.actual_installed_app);
  const terminals = [];
  page.on('websocket', socket => socket.on('framereceived', event => {
    try {
      const frame = JSON.parse(String(event.payload));
      if (['assistant_complete', 'assistant_error', 'assistant_partial', 'turn_end'].includes(frame.event_type)) terminals.push(frame);
    } catch { /* ignore non-protocol traffic */ }
  }));
  const input = page.getByRole('textbox', { name: '聊天输入', exact: true });
  const skip = page.getByRole('button', { name: '暂时跳过，使用模板教学', exact: true });
  await waitFor(async () => await skip.isVisible() || await input.isVisible(), 90000, 'onboarding');
  if (await skip.isVisible()) await skip.click();
  await input.waitFor();
  const configuration = await page.evaluate(async () => {
    const r = await fetch('/api/v2/math-tutor/desktop/exploration/configuration');
    return r.json();
  });
  assert(configuration.configured && configuration.environment_managed && !configuration.has_saved_secret);

  // Reload the chat through its public entry so the observer sees its original WebSocket.
  await page.goto(origin + '/math-tutor');
  await waitFor(() => input.isEnabled().catch(() => false), 30000, 'a connected chat');
  const online = page.getByRole('button', { name: '联网', exact: true });
  if (await online.getAttribute('aria-pressed') !== 'true') await online.click();
  const question = '我能把括号展开，但常分不清什么时候该合并同类项。请从知乎找一份合适的入门资料，安排一次不超过十分钟的练习：先看什么，再做什么，最后怎样核对。';
  await input.fill(question);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await waitFor(() => terminals.some(f => f.event_type === 'turn_end'), 135000, 'the source-grounded answer');
  const answer = terminals.findLast(f => f.event_type === 'assistant_complete');
  assert(answer && !/额度或频率受限|请求过于频繁/.test(answer.payload.final_text), 'The online service could not complete this turn');
  const receipt = readReceipt(answer.payload.turn_id);
  assert(['answered', 'partial'].includes(receipt.status), 'A sourced reply is required');
  await page.locator('a[href*="zhihu.com/"]').first().waitFor({ state: 'visible' });
  const visibleLinks = await page.locator('a[href*="zhihu.com/"]').evaluateAll(links => links.map(link => link.href));
  const visibleText = await page.locator('body').innerText();
  report.cases.E05 = { citations: checkCitations(receipt, visibleLinks, visibleText), status: 'matched_visible_source_quotes' };
  assert.equal(receipt.planner.goal, 'combine_like_terms');
  assert.equal(receipt.planner.steps.reduce((total, step) => total + step.minutes, 0), 10);
  const selectedResource = receipt.planner.resources[0];
  assert(selectedResource?.url && selectedResource.selection_reason && visibleLinks.includes(selectedResource.url), 'The selected reading needs a visible link and a reason');
  report.cases.E02 = { selected: selectedResource.title, reason: selectedResource.selection_reason, url: selectedResource.url, goal: receipt.planner.goal, plan: receipt.planner.rendered_text, answer: answer.payload.final_text, status: 'review_recommendation' };
  assert(['zhihu.com', 'www.zhihu.com', 'zhuanlan.zhihu.com'].includes(new URL(selectedResource.url).hostname));
  assert(receipt.planner.rendered_text.includes(selectedResource.title)
    && receipt.planner.rendered_text.includes('](' + selectedResource.url + ')'), 'The plan must name and link the selected article');
  save();

  await page.goto(origin + '/math-tutor/explore');
  await page.getByPlaceholder('写一个具体的数学问题').fill('为什么分数相加之前要通分？');
  await page.getByRole('radio', { name: '知乎问答', exact: true }).check();
  await page.locator('input[name="exploration-goal"][value="compare"]').check();
  const pending = page.waitForResponse(response => response.url().includes('/exploration/inquiries') && response.request().method() === 'POST', { timeout: 65000 });
  await page.getByRole('button', { name: '开始探索', exact: true }).click();
  const response = await pending;
  assert.equal(response.ok(), true, 'Search on the installed service failed');
  const { evidence } = await response.json();
  assert(evidence.sources.length >= 2 && evidence.sources.every(source => source.provider === 'zhihu' && source.request_id && source.scope === 'search_excerpt'));
  const selected = [evidence.cards[0], evidence.cards.find(card => card.source_id !== evidence.cards[0].source_id)];
  assert(selected[1], 'Two distinct community sources are required');
  for (const card of selected) {
    const source = evidence.sources.find(s => s.source_id === card.source_id);
    assert(source.text.includes(card.quote));
    await page.getByRole('checkbox', { name: /对照摘录/ }).nth(evidence.cards.indexOf(card)).check();
  }
  const comparison = page.getByRole('region', { name: '把条件放在一起看' });
  const visible = await comparison.innerText();
  const details = selected.map(card => {
    assert(visible.includes(card.title) && visible.includes(card.quote));
    assert(visible.includes(card.author || '作者未提供'));
    return { title: card.title, author: card.author, url: card.original_url, quote: card.quote, quote_sha256: sha(card.quote) };
  });
  report.cases.E01 = { status: 'review_relevance', query: '为什么分数相加之前要通分？', sources: details };
  report.cases.E03 = { status: 'received', request_ids: [...new Set(evidence.sources.map(s => s.request_id))] };
  report.cases.E04 = { status: 'visible', sources: details };
  report.cases.E07 = { status: 'paired_original_excerpts', sources: details };
  await page.screenshot({ path: path.join(args.output, 'source-comparison.png') });

  await app.evaluate(({ shell }) => {
    const open = shell.openExternal.bind(shell);
    globalThis.acceptedSourceLinks = [];
    shell.openExternal = async (url, options) => {
      await open(url, options);
      globalThis.acceptedSourceLinks.push(url);
    };
  });
  await comparison.getByRole('link', { name: '打开知乎原文' }).first().click();
  await waitFor(async () => (await app.evaluate(() => globalThis.acceptedSourceLinks)).includes(selected[0].original_url), 12000, 'OS handoff to the original source');
  assert.equal(new URL(page.url()).origin, origin);
  report.cases.E06 = { status: 'accepted_by_os', url: selected[0].original_url };
  report.automatic_scope = 'complete';
} catch (error) {
  report.error = String(error.message);
  process.exitCode = 1;
} finally {
  report.finished_at = new Date().toISOString();
  save();
  if (page && !page.isClosed()) {
    for (const field of await page.locator('textarea:visible').all()) await field.fill('').catch(() => {});
  }
  await app.close();
}

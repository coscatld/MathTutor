import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const flags = Object.fromEntries(process.argv.slice(2).flatMap((v, i, all) => v.startsWith('--') ? [[v.slice(2), all[i + 1]?.startsWith('--') ? true : all[i + 1] ?? true]] : []));
const here = path.dirname(fileURLToPath(import.meta.url));
const cases = ['E08', 'E09', 'E10', 'F05'];
const stamp = () => new Date().toISOString();
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const redact = value => JSON.parse(JSON.stringify(value, (key, item) => /^(?:api_key|authorization|token|access_token|refresh_token|secret|native_bridge_secret)$/i.test(key) ? '[redacted]' : item));
const loopback = value => { try { const u = new URL(value); return ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname) && ['http:', 'ws:'].includes(u.protocol); } catch { return false; } };
function emptyInquiry(body) {
  return {
    inquiry_id: body.inquiry_id, question: body.question, goal: body.goal, revision: 1, updated_at: stamp(), reflection: '',
    evidence: { question: body.question, sources: [], spans: [], cards: [], interpretations: [], comparisons: [], gaps: [{ code: 'no_usable_sources', source_ids: [] }], rejected_candidate_items: [], source_rejections: [], unselected_source_ids: [], distinct_excerpt_count: 0, status: 'no_evidence' },
    learning: { policy: 'exploration_learning_v1', original_question: body.question, goal: body.goal, target_concept: '', concept_title: '', evidence_state: 'unknown', independent_successes: 0, basis_observation_ids: [], steps: [], check: null, prerequisite_basis: 'none' },
    ai_status: 'not_requested', organization_attempts: 0, last_feedback: '', last_check: null, last_correctness: null, observation_count: 0,
  };
}
if (flags['self-test']) {
  assert(loopback('http://127.0.0.1:1234/api/chat'));
  assert(!loopback('https://developer.zhihu.com'));
  assert.equal(emptyInquiry({ inquiry_id: 'synthetic', question: '公开问题', goal: 'understand' }).evidence.cards.length, 0);
  console.log(JSON.stringify({ status: 'HARNESS_SMOKE_PASS', installed_app_run: false, provider_calls: 0, cases }));
  process.exit(0);
}
assert(flags.executable && flags.output, '--executable and --output required');
const executable = path.resolve(flags.executable), output = path.resolve(flags.output);
const data = flags['data-root'] ? path.resolve(flags['data-root']) : fs.mkdtempSync(path.join(os.tmpdir(), 'mathtutor-installed-fault-'));
assert(fs.statSync(executable).isFile());
assert(!fs.existsSync(path.join(output, 'installed-fault-acceptance.json')), 'Use a fresh output directory');
assert(!fs.existsSync(path.join(data, 'math_tutor.db')), 'Use a fresh isolated data root');
fs.mkdirSync(output, { recursive: true }); fs.mkdirSync(data, { recursive: true });
const chosen = flags.only ? String(flags.only).split(',') : cases;
assert(chosen.every(id => cases.includes(id)));
const matrixPath = path.join(here, 'installed-product-cases.json');
const matrix = JSON.parse(fs.readFileSync(matrixPath, 'utf8'));
const resources = process.platform === 'darwin' ? path.resolve(executable, '../../Resources') : path.join(path.dirname(executable), 'resources');
const identity = { executable, executable_sha256: sha(fs.readFileSync(executable)), app_asar_sha256: sha(fs.readFileSync(path.join(resources, 'app.asar'))), installer_sha256: flags['installer-sha256'] || null, platform: process.platform, architecture: process.arch, data_root: data, matrix_sha256: sha(fs.readFileSync(matrixPath)), driver_sha256: sha(fs.readFileSync(fileURLToPath(import.meta.url))) };
identity.packaged_files = Object.fromEntries(['application/exploration.py', 'infrastructure/zhihu.py', 'application/tutor_runtime.py', 'api/math_tutor_ws.py', 'infrastructure/generative_gateway.py'].map(name => [name, sha(fs.readFileSync(path.join(resources, 'python-app/mathtutor', name)))]));
const results = matrix.cases.filter(c => cases.includes(c.id)).map(c => ({ ...c, status: 'not_run' }));
const frames = [], requests = [], injected = [], provider = [], errors = [], blockedExternal = [];
let application, page, base, currentCase = null, mode = 'idle', launches = 0, providerCalls = 0, originalSession = null;
const started = stamp();
const write = (name, value) => fs.writeFileSync(path.join(output, name), JSON.stringify(redact(value), null, 2) + '\n');
function save() {
  write('installed-fault-acceptance.json', { started_at: started, updated_at: stamp(), identity, actual_installed_app: launches > 0, source_testclient: false, developer_server: false,
    real_provider_calls: 0, local_synthetic_provider_calls: providerCalls, credentials_written: false, production_bundle_modified: false,
    scope: { E08: 'Installed renderer HTTP connection-abort injection; no Zhihu backend/provider invocation', E09: 'Installed renderer HTTP 502 injection; no Zhihu backend/provider invocation', E10: 'Installed renderer empty inquiry response injection; no backend empty Items processing claimed', F05: 'Installed original backend Ollama adapter receives local HTTP truncated response then upstream HTTP 503; original WS, SQLite, UI and restart' },
    results, blocked_external_requests: blockedExternal, page_errors: errors,
    automatic_scope: { planned: chosen.length, passed: results.filter(r => chosen.includes(r.id) && r.status === 'passed').length, failed: results.filter(r => chosen.includes(r.id) && r.status === 'failed').length },
    overall_product_acceptance: 'incomplete_separate_fault_scope_only' });
  write('protocol-frames.json', frames); write('same-origin-requests.json', requests); write('injections.json', injected); write('local-provider-requests.json', provider);
}
const localServer = http.createServer(async (req, res) => {
  const chunks = []; for await (const chunk of req) chunks.push(chunk);
  let body = null; try { body = JSON.parse(Buffer.concat(chunks).toString()); } catch { /* Empty GET body. */ }
  const record = { at: stamp(), case: currentCase, method: req.method, path: req.url, request: body, injection: 'local HTTP adapter; no real model' };
  assert(!req.headers.authorization, 'Ollama adapter unexpectedly sent credentials');
  provider.push(record);
  const respond = (status, value) => { record.response = { status, body: value }; res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); };
  if (req.method === 'GET' && req.url === '/api/tags') return respond(200, { models: [{ name: 'fault-acceptance-local', model: 'fault-acceptance-local' }] });
  if (req.url === '/api/show') return respond(200, { capabilities: [] });
  if (req.method !== 'POST' || req.url !== '/api/chat') { blockedExternal.push({ at: stamp(), layer: 'backend proxy', method: req.method, url: req.url }); return respond(502, { error: 'External traffic disabled in acceptance' }); }
  providerCalls++;
  if (providerCalls === 1) return respond(200, { model: 'fault-acceptance-local', message: { role: 'assistant', content: '定义先约定讨论对象；结论是在给定条件下推出的判断。接下来还需要说明条件如何参与推理。' }, done: true, done_reason: 'length', prompt_eval_count: 40, eval_count: 30 });
  if (providerCalls === 3) return respond(200, { model: 'fault-acceptance-local', message: { role: 'assistant', content: '条件限定了结论成立的范围，因此检查条件能避免把结论用到不适用的对象。' }, done: true, done_reason: 'stop', prompt_eval_count: 60, eval_count: 25 });
  respond(503, { error: 'CONTROLLED_ACCEPTANCE_UPSTREAM_INTERRUPTION' });
});
localServer.on('connect', (req, socket) => { blockedExternal.push({ at: stamp(), layer: 'backend CONNECT proxy', url: req.url }); socket.end('HTTP/1.1 502 Acceptance network disabled\r\n\r\n'); });
await new Promise(resolve => localServer.listen(0, '127.0.0.1', resolve));
const providerBase = `http://127.0.0.1:${localServer.address().port}`;
const config = { config_version: 2, revision: 1, preset_id: 'ollama', base_url: providerBase, model: 'fault-acceptance-local', provider_configs: { ollama: { base_url: providerBase, model: 'fault-acceptance-local', vision_mode: 'disabled' } }, roles: ['tutor_writer', 'practice_generator'], onboarding_completed: true };
fs.writeFileSync(path.join(data, 'gateway.json'), JSON.stringify(config));
write('nonsecret-local-provider-setup.json', { setup: 'Existing persisted Ollama configuration in fresh disposable data root; no secret field or credentials API', config });
const { _electron } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
function environment() {
  const allowed = ['HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'DISPLAY', 'XAUTHORITY'];
  const env = Object.fromEntries(allowed.filter(k => process.env[k]).map(k => [k, process.env[k]]));
  return { ...env, PATH: process.platform === 'win32' ? `${process.env.SystemRoot}\\System32;${process.env.SystemRoot}` : '/usr/bin:/bin:/usr/sbin:/sbin', MATHTUTOR_DATA_ROOT: data, CUDA_VISIBLE_DEVICES: '', OMP_NUM_THREADS: '1', OPENBLAS_NUM_THREADS: '1', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1', HTTP_PROXY: providerBase, HTTPS_PROXY: providerBase, ALL_PROXY: providerBase, NO_PROXY: '127.0.0.1,localhost,::1' };
}
async function until(test, timeout = 30000, label = 'condition') {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await test()) return; await pause(100); }
  throw new Error(`Timed out: ${label}`);
}
async function launch() {
  application = await _electron.launch({ executablePath: executable, args: [`--user-data-dir=${path.join(data, 'chromium')}`], env: environment(), cwd: path.dirname(data), timeout: 120000 });
  launches++;
  page = await application.firstWindow({ timeout: 120000 }); page.setDefaultTimeout(20000);
  page.on('dialog', dialog => { void dialog.accept().catch(error => injected.push({ at: stamp(), case: currentCase, transient_dialog_race: error.message })); });
  page.on('pageerror', error => errors.push({ at: stamp(), case: currentCase, message: error.message }));
  page.on('websocket', socket => {
    if (!loopback(socket.url())) return;
    for (const [event, direction] of [['framesent', 'sent'], ['framereceived', 'received']]) socket.on(event, eventData => {
      try { frames.push({ at: stamp(), case: currentCase, direction, frame: JSON.parse(String(eventData.payload)) }); } catch { /* Non-product frame. */ }
    });
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (!loopback(request.url())) { if (['http:', 'https:'].includes(url.protocol)) { blockedExternal.push({ at: stamp(), layer: 'renderer', url: request.url() }); return route.abort('blockedbyclient'); } return route.continue(); }
    const body = request.postDataJSON();
    if (url.pathname === '/api/v2/math-tutor/desktop/exploration/configuration') {
      assert.equal(request.method(), 'GET', 'Credentials must not be written');
      const value = { configured: true, environment_managed: true, persistent: false, has_saved_secret: false };
      injected.push({ at: stamp(), case: currentCase, path: url.pathname, method: 'GET', response: value, purpose: 'Renderer-only connectivity fixture, prevents any credential read' });
      return route.fulfill({ status: 200, json: value });
    }
    if (url.pathname === '/api/v2/math-tutor/desktop/exploration/inquiries' && request.method() === 'POST') {
      const record = { at: stamp(), case: currentCase, path: url.pathname, request: body, injection_layer: 'Chromium request routing before backend', mode };
      injected.push(record);
      assert.equal(body.question, '为什么函数连续不一定可导？');
      assert.deepEqual(Object.keys(body).sort(), ['generation', 'goal', 'inquiry_id', 'language', 'question']);
      if (mode === 'connection_abort') { record.abort = 'connectionrefused'; return route.abort('connectionrefused'); }
      if (mode === 'api_failure') { record.response = { status: 502, body: { detail: '知乎服务暂时无法完成请求，请稍后再试。' } }; return route.fulfill({ status: 502, json: record.response.body }); }
      if (mode === 'empty') { record.response = { status: 200, body: emptyInquiry(body) }; return route.fulfill({ status: 200, json: record.response.body }); }
      throw new Error('No live exploration POST is permitted');
    }
    await route.continue();
  });
  await page.waitForURL(url => loopback(url.href), { timeout: 120000 });
  base = new URL(page.url()).origin;
  identity.electron = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, version: app.getVersion(), app_path: app.getAppPath(), resources: process.resourcesPath }));
  assert.equal(identity.electron.packaged, true);
  write(`running-process-${launches}.json`, { pid: application.process().pid, executable, data_root: data, url: page.url(), at: stamp() });
  await until(async () => await page.getByRole('textbox', { name: '聊天输入', exact: true }).count() || await page.getByRole('button', { name: '暂时跳过，使用模板教学', exact: true }).count(), 90000, 'product chat');
  const skip = page.getByRole('button', { name: '暂时跳过，使用模板教学', exact: true });
  if (await skip.isVisible().catch(() => false)) throw new Error('Preloaded local Ollama configuration did not restore');
}
async function api(suffix) {
  const result = await page.evaluate(async suffix => { const response = await fetch('/api/v2/math-tutor' + suffix, { headers: { 'X-MathTutor-CSRF': '1' } }); return { status: response.status, body: await response.json() }; }, suffix);
  requests.push({ at: stamp(), case: currentCase, path: suffix, method: 'GET', response: result }); assert.equal(result.status, 200); return result.body;
}
async function navigate(suffix) { await page.goto(base + suffix, { waitUntil: 'domcontentloaded' }); await page.waitForURL(url => url.pathname === new URL(base + suffix).pathname); }
async function capture(name) { write(`${name}-visible.json`, { at: stamp(), url: page.url(), body: await page.locator('body').innerText() }); await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true }); }
async function closeApplication() {
  if (!application) return;
  for (const label of ['聊天输入', '你想弄清什么？']) {
    const input = page.getByRole('textbox', { name: label, exact: true });
    if (await input.isVisible().catch(() => false) && await input.isEnabled().catch(() => false)) await input.fill('');
  }
  await pause(100);
  const owned = application, pid = owned.process().pid;
  let timeout;
  try { await Promise.race([owned.close(), new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('Installed app did not close within 15 seconds')), 15000); })]); }
  catch (error) { injected.push({ at: stamp(), case: currentCase, layer: 'QA cleanup', owned_pid: pid, forced_stop: true, reason: error.message }); owned.process().kill('SIGKILL'); throw error; }
  finally { clearTimeout(timeout); application = null; }
}
async function run(id, operation) {
  if (!chosen.includes(id)) return;
  currentCase = id; const row = results.find(r => r.id === id), first = frames.length, errorCount = errors.length, begin = Date.now(); row.started_at = stamp();
  try { row.observation = await operation(); assert.equal(errors.length, errorCount, 'Uncaught renderer error'); assert.equal(blockedExternal.length, 0, 'Unexpected external request attempt'); row.status = 'passed'; } catch (error) { row.status = 'failed'; row.reason = error.message; row.error = error.stack; }
  finally { row.elapsed_seconds = (Date.now() - begin) / 1000; row.finished_at = stamp(); try { await capture(id); } catch (error) { row.capture_error = error.message; } write(`${id}-protocol.json`, frames.slice(first)); save(); console.log(JSON.stringify({ case: id, status: row.status, reason: row.reason })); currentCase = null; }
}
async function explorationFault(which) {
  mode = which;
  await navigate('/math-tutor/explore');
  const input = page.getByRole('textbox', { name: '你想弄清什么？', exact: true });
  await input.fill('为什么函数连续不一定可导？');
  const submit = page.getByRole('button', { name: '开始探索', exact: true });
  await until(() => submit.isEnabled(), 30000, 'exploration enabled');
  const before = injected.length; await submit.click();
  if (which === 'empty') {
    await page.getByRole('heading', { name: '还没有可用的来源摘录', exact: true }).waitFor();
    assert.equal(await page.locator('a[href*="zhihu.com/"]').count(), 0);
    assert.equal(await page.getByRole('button', { name: 'AI 整理阅读问题', exact: true }).isEnabled(), false);
    return { classification: 'renderer_only_empty_response', request: injected.slice(before), no_source_links: true, no_fake_content: true, backend_empty_items_not_tested: true };
  }
  const alert = page.getByRole('alert').filter({ hasText: which === 'api_failure' ? '知乎服务暂时无法完成请求' : '请求未完成' }); await alert.waitFor();
  const message = await alert.innerText();
  assert(which === 'api_failure' ? /知乎服务暂时无法完成请求/.test(message) : /请求未完成.*重试/.test(message), message);
  assert(!/没有.*(?:来源|结果)|未找到/.test(message), 'Failure disguised as empty results');
  assert.equal(await input.inputValue(), '为什么函数连续不一定可导？');
  assert.equal(await page.locator('a[href*="zhihu.com/"]').count(), 0);
  await capture(`${currentCase}-failure`);
  await page.getByRole('button', { name: '同步记录', exact: true }).click();
  await until(() => submit.isEnabled(), 30000, 'retry after record sync');
  assert.equal(await input.inputValue(), '为什么函数连续不一定可导？');
  assert.equal(injected.slice(before).filter(v => v.method !== 'GET').length, 1, 'Unexpected automatic retry');
  await input.fill('');
  return { classification: 'renderer_only_transport_injection', notice: message, draft_retained: true, retry_enabled_after_sync: true, automatic_retry_count: 0, backend_provider_not_invoked: true };
}
try {
  save(); await launch();
  await run('E08', () => explorationFault('connection_abort'));
  await run('E09', () => explorationFault('api_failure'));
  await run('E10', () => explorationFault('empty'));
  await run('F05', async () => {
    mode = 'idle'; await navigate('/math-tutor');
    await page.waitForURL(url => url.pathname === '/math-tutor' && Boolean(url.searchParams.get('session')));
    const input = page.getByRole('textbox', { name: '聊天输入', exact: true }); await until(() => input.isEnabled(), 30000, 'chat connection');
    const before = await api('/desktop/student-evidence'); const first = frames.length;
    originalSession = new URL(page.url()).searchParams.get('session');
    await input.fill('数学概念里，定义和结论有什么区别？'); await page.getByRole('button', { name: '发送', exact: true }).click();
    await until(() => frames.slice(first).some(f => ['assistant_complete', 'assistant_partial', 'assistant_error'].includes(f.frame.event_type)), 120000, 'original backend terminal');
    const terminal = frames.slice(first).find(f => ['assistant_complete', 'assistant_partial', 'assistant_error'].includes(f.frame.event_type)).frame;
    assert.equal(terminal.event_type, 'assistant_partial', JSON.stringify(terminal));
    assert.equal(terminal.payload.status, 'PARTIAL');
    assert.equal(terminal.payload.finish_reason, 'PROVIDER_ERROR');
    assert(providerCalls >= 2 && providerCalls <= 3, `Unexpected upstream retry count ${providerCalls}`);
    await page.getByText('这段还没讲完，末尾的公式和结论可能不完整。', { exact: false }).waitFor();
    await capture('F05-before-restart');
    const persisted = await api('/sessions/' + originalSession);
    const partial = persisted.messages.find(m => m.role === 'tutor' && m.status === 'PARTIAL');
    assert(partial && /定义先约定/.test(partial.content), 'Partial text missing from real persistent session');
    assert.equal(partial.finish_reason, 'PROVIDER_ERROR');
    assert.deepEqual(await api('/desktop/student-evidence'), before, 'Partial explanation created learning mastery');
    const originalDraft = await input.inputValue();
    save(); await closeApplication(); await launch();
    await navigate('/math-tutor?session=' + encodeURIComponent(originalSession));
    await page.getByText('这段还没讲完，末尾的公式和结论可能不完整。', { exact: false }).waitFor();
    const reopened = await api('/sessions/' + originalSession);
    assert(reopened.messages.some(m => m.status === 'PARTIAL' && m.content === partial.content && m.finish_reason === 'PROVIDER_ERROR'));
    assert.equal(providerCalls, 2, 'Restart unexpectedly retried provider');
    await capture('F05-after-restart');
    write('F05-durable-checks.json', { terminal, persisted, reopened, original_draft: originalDraft, partial_retained_after_restart: true, mastery_unchanged: true });
    assert.equal(originalDraft, '', 'Accepted partial reply must not invite resending the persisted original question');
    assert((await page.locator('body').innerText()).includes('模型服务暂时不可用。'), 'The interruption reason is not visible to the learner');
    const continuation = frames.length;
    await page.getByRole('button', { name: '继续讲完', exact: true }).click();
    await until(() => frames.slice(continuation).some(f => f.frame.event_type === 'assistant_complete'), 30000, 'real continuation');
    const continued = await api('/sessions/' + originalSession);
    assert.equal(continued.messages.filter(m => m.role === 'student' && m.content === '数学概念里，定义和结论有什么区别？').length, 1, 'Continuation duplicated the original question');
    assert.equal(continued.messages.filter(m => m.role === 'tutor' && m.content === partial.content).length, 1, 'Continuation duplicated the partial answer');
    assert(continued.messages.some(m => m.role === 'student' && m.content === '继续'));
    assert(continued.messages.some(m => m.role === 'tutor' && m.status === 'COMPLETED' && m.content.includes('条件限定了')));
    assert.equal(providerCalls, 3, 'Unexpected provider retry count after explicit continuation');
    return { classification: 'original_backend_local_upstream_http_injection', question: '数学概念里，定义和结论有什么区别？', local_response_sequence: ['200 done_reason=length', '503 controlled interruption', 'explicit Continue: 200 stop'], terminal, persisted, reopened, continued, partial_retained_after_restart: true, mastery_unchanged: true, real_model: false };
  });
} catch (error) { write('fatal.json', { message: error.message, stack: error.stack }); console.error(error.stack); }
finally {
  if (application) await closeApplication().catch(() => {});
  await new Promise(resolve => localServer.close(resolve));
  for (const name of ['startup.log', 'startup.previous.log']) { const source = path.join(data, 'logs', name); if (fs.existsSync(source)) fs.copyFileSync(source, path.join(output, name)); }
  save();
}
process.exitCode = chosen.every(id => results.find(r => r.id === id).status === 'passed') ? 0 : 1;

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath, pathToFileURL } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
function parseFlags(values) {
    const parsed = {};
    for (let index = 0; index < values.length; index++) {
        const name = values[index];
        assert(name.startsWith('--'), `Unexpected argument: ${name}`);
        const next = values[index + 1];
        parsed[name.slice(2)] = !next || next.startsWith('--') ? true : values[++index];
    }
    return parsed;
}

const flags = parseFlags(process.argv.slice(2));
const matrixPath = path.resolve(flags.matrix || path.join(here, 'installed-product-cases.json'));
const matrix = JSON.parse(fs.readFileSync(matrixPath, 'utf8'));
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const stamp = () => new Date().toISOString();
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const sensitiveField = /^(?:api_key|authorization|token|access_token|refresh_token|secret|native_bridge_secret)$/i;
const redact = value => JSON.parse(JSON.stringify(value, (key, item) => sensitiveField.test(key) ? '[redacted]' : item));
const normalize = text => text
    .replace(/\\(?:dfrac|frac)\{([^}]*)\}\{([^}]*)\}/g, '$1/$2')
    .replace(/[\s{}()$\\]/g, '')
    .replaceAll('−', '-')
    .replaceAll('＜', '<')
    .replaceAll('＝', '=');
const isLoopback = value => {
    const url = new URL(value);
    return url.protocol === 'http:' && url.hostname === '127.0.0.1';
};
const automatic = [
    'L01',
    'A01', 'A02', 'A03', 'A04', 'A05', 'A06', 'A07', 'A08',
    'B01', 'B02', 'B03', 'B04', 'B05',
    'C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07',
    'D01', 'D02', 'D03', 'D04', 'D05', 'D06',
    'F01', 'F02', 'F03', 'F04', 'F06', 'F07',
];
if (flags['self-test']) {
    assert.equal(new Set(matrix.cases.map(c => c.id)).size, 44);
    assert(automatic.every(id => matrix.cases.some(c => c.id === id)));
    assert.equal(normalize('x = \\frac{7}{8}'), 'x=7/8');
    assert.equal(redact({ api_key: 'synthetic', nested: { authorization: 'synthetic' } }).nested.authorization, '[redacted]');
    assert(isLoopback('http://127.0.0.1:12345/math-tutor'));
    assert(!isLoopback('https://example.org'));
    console.log(JSON.stringify({
        at: stamp(), status: 'HARNESS_SMOKE_PASS', installed_app_run: false, cases: matrix.cases.length, automatic: automatic.length, provider_calls: 0
    }));
    process.exit(0);
}
assert(flags.executable && flags.output, '--executable and --output are required');
const executable = path.resolve(flags.executable);
assert(fs.statSync(executable).isFile(), 'Installed executable required');
const output = path.resolve(flags.output);
fs.mkdirSync(output, { recursive: true });
const data = flags['data-root'] ? path.resolve(flags['data-root']) : fs.mkdtempSync(path.join(os.tmpdir(), 'mathtutor-installed-product-'));
assert(!fs.existsSync(path.join(data, 'math_tutor.db')), 'Acceptance requires a fresh disposable data root');
fs.mkdirSync(data, { recursive: true });
const chosen = flags.only ? String(flags.only).split(',').map(s => s.trim()) : automatic;
assert(chosen.every(id => automatic.includes(id)), 'Unsupported --only case');
const packageResources = process.platform === 'darwin' ? path.resolve(executable, '../../Resources') : path.join(path.dirname(executable), 'resources');
const identity = {
    executable, executable_sha256: hash(fs.readFileSync(executable)), resources: packageResources,
    app_asar_sha256: fs.existsSync(path.join(packageResources, 'app.asar')) ? hash(fs.readFileSync(path.join(packageResources, 'app.asar'))) : null,
    installer_sha256: flags['installer-sha256'] || null, platform: process.platform, architecture: process.arch, data_root: data,
    matrix_sha256: hash(fs.readFileSync(matrixPath)), driver_sha256: hash(fs.readFileSync(fileURLToPath(import.meta.url)))
};
identity.packaged_files = Object.fromEntries([
    'python-app/mathtutor/application/controller.py',
    'python-app/mathtutor/application/input_normalizer.py',
    'python-app/mathtutor/application/constraint_layer.py',
    'python-app/mathtutor/application/math_operation_scope.py',
    'python-app/mathtutor/application/math_claims.py',
    'python-app/mathtutor/application/learning_actions.py',
    'python-app/mathtutor/application/network_qa.py',
    'python-app/mathtutor/application/recommendations.py',
    'web/.next-mathtutor/BUILD_ID', 'web/.next/BUILD_ID',
].filter(name => fs.existsSync(path.join(packageResources, name))).map(name => [name, hash(fs.readFileSync(path.join(packageResources, name)))]));
const results = matrix.cases.map(c => ({
    ...c, status: 'not_run', reason: chosen.includes(c.id) ? 'Awaiting installed execution' : 'Outside automatic scope; requires separately identified evidence'
}));
const frames = [], errors = [], requests = [], navigation = [], shared = {};
let application, page, base, currentCase = null, launches = 0, closing = false;
const write = (filename, value) => fs.writeFileSync(path.join(output, filename), JSON.stringify(redact(value), null, 2) + '\n');
const resultFor = id => results.find(c => c.id === id);
const save = () => write('installed-product-acceptance.json', {
    started_at: started, updated_at: stamp(), identity, live_provider_calls: 0,
    actual_installed_app: launches > 0, developer_server: false, source_testclient: false, results,
    automatic_scope: {
        planned: chosen.length, passed: results.filter(r => chosen.includes(r.id) && r.status === 'passed').length, failed: results.filter(r => chosen.includes(r.id) && r.status === 'failed').length, needs_review: results.filter(r => chosen.includes(r.id) && r.status === 'needs_review').length
    },
    overall_product_acceptance: results.every(r => r.status === 'passed') ? 'passed' : 'incomplete_or_failed', page_errors: errors
});
const started = stamp();
const mod = process.env.PLAYWRIGHT_MODULE;
const { _electron } = await import(mod && path.isAbsolute(mod) ? pathToFileURL(mod).href : mod || 'playwright');
function cleanEnvironment() {
    const allowed = ['HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'DISPLAY', 'XAUTHORITY'];
    const env = Object.fromEntries(allowed.filter(key => process.env[key]).map(key => [key, process.env[key]]));
    env.PATH = process.platform === 'win32' ? `${process.env.SystemRoot}\\System32;${process.env.SystemRoot}` : '/usr/bin:/bin:/usr/sbin:/sbin';
    return {
        ...env, MATHTUTOR_DATA_ROOT: data, CUDA_VISIBLE_DEVICES: '', OMP_NUM_THREADS: '1', OPENBLAS_NUM_THREADS: '1', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1'
    };
}

async function until(check, timeout = 30000, label = 'condition') {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
        if (await check())
            return;
        await delay(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
}

async function launch() {
    application = await _electron.launch({
        executablePath: executable, args: [`--user-data-dir=${path.join(data, 'chromium')}`], env: cleanEnvironment(), cwd: path.dirname(data), timeout: 120000
    });
    launches++;
    write('running-process.json', {
        pid: application.process().pid, executable, data_root: data, chromium_profile: path.join(data, 'chromium'), started_at: stamp()
    });
    page = await application.firstWindow({ timeout: 120000 });
    page.setDefaultTimeout(20000);
    page.on('dialog', dialog => {
        const record = {at: stamp(), case: currentCase, native_dialog: dialog.type(), message: dialog.message(), action: closing ? 'accept' : 'dismiss'};
        requests.push(record);
        const handling = closing ? dialog.accept() : dialog.dismiss();
        handling.catch(error => { record.handling_error = error.message; }).finally(() => {
            write('native-dialogs.json', requests.filter(item => item.native_dialog));
        });
    });
    page.on('framenavigated', frame => {
        if (frame === page.mainFrame())
            navigation.push({
                at: stamp(), case: currentCase, url: frame.url()
            });
    });
    await page.bringToFront();
    page.on('pageerror', error => errors.push({
        at: stamp(), case: currentCase, message: error.message
    }));
    page.on('websocket', socket => {
        if (!/\/api\//.test(socket.url()))
            return;
        for (const [event, direction] of [['framesent', 'sent'], ['framereceived', 'received']])
            socket.on(event, eventData => {
                try {
                    frames.push({
                        at: stamp(), case: currentCase, direction, frame: JSON.parse(String(eventData.payload))
                    });
                }
                catch {
                }
            });
    });
    await page.waitForURL(url => isLoopback(url.href), { timeout: 120000 });
    base = new URL(page.url()).origin;
    assert(isLoopback(base));
    await until(async () => await page.getByRole('textbox', { name: '聊天输入', exact: true }).count() > 0 || await page.getByRole('button', { name: '暂时跳过，使用模板教学', exact: true }).count() > 0, 90000, 'normal onboarding or chat');
    const skip = page.getByRole('button', { name: '暂时跳过，使用模板教学', exact: true });
    if (await skip.isVisible().catch(() => false))
        await skip.click();
    await page.getByRole('textbox', { name: '聊天输入', exact: true }).waitFor();
    const settings = await api('/desktop/settings');
    assert.equal(settings.is_configured, false, 'Real provider is configured; this credential-free driver will not use or overwrite it');
    identity.electron = await application.evaluate(({ app }) => ({
        packaged: app.isPackaged, version: app.getVersion(), app_path: app.getAppPath(), resources: process.resourcesPath
    }));
    assert.equal(identity.electron.packaged, true, 'A source Electron launch is not installed-package acceptance');
    await goto('/math-tutor');
    await connected();
}

async function api(suffix, { method = 'GET', body } = {}) {
    assert(suffix.startsWith('/desktop/') || suffix.startsWith('/sessions'), 'Only product same-origin API allowed');
    const result = await page.evaluate(async ({ suffix, method, body }) => {
        const response = await fetch('/api/v2/math-tutor' + suffix, {
            method, headers: { 'X-MathTutor-CSRF': '1', 'Content-Type': 'application/json' }, ...(body !== undefined ? { body: JSON.stringify(body) } : {})
        });
        const text = await response.text();
        let value;
        try {
            value = JSON.parse(text);
        }
        catch {
            value = { text };
        }
        return { status: response.status, body: value };
    }, {
        suffix, method, body
    });
    requests.push({
        at: stamp(), case: currentCase, path: suffix, method, request: body, response: result
    });
    assert(result.status >= 200 && result.status < 300, `Same-origin ${method} ${suffix}: HTTP ${result.status}`);
    return result.body;
}

async function connected() {
    await page.waitForURL(url => url.pathname === '/math-tutor' && Boolean(url.searchParams.get('session')));
    await until(async () => await page.getByRole('textbox', {name: /^(聊天输入|Chat input)$/}).isEnabled(), 30000, 'original WebSocket connection');
    await page.waitForLoadState('networkidle');
}

async function goto(suffix) {
    const target = new URL(base + suffix);
    await page.goto(target.href, { waitUntil: 'domcontentloaded' });
    await page.waitForURL(url => url.pathname === target.pathname);
    if (target.pathname === '/math-tutor')
        await connected();
    else {
        await page.locator('#workspace-content').waitFor();
        await page.waitForLoadState('domcontentloaded');
    }
}

async function newChat() {
    const previous = new URL(page.url()).searchParams.get('session');
    const oldDraft = page.getByRole('textbox', {name: '聊天输入', exact: true});
    if (await oldDraft.isVisible().catch(() => false) && await oldDraft.inputValue()) {
        const cleared = await oldDraft.inputValue();
        await oldDraft.clear();
        requests.push({at: stamp(), case: currentCase, setup: 'Cleared previous case draft through actual UI', previous_draft: cleared});
    }
    await page.getByRole('button', { name: '新建对话', exact: true }).first().click();
    await page.waitForURL(url => url.pathname === '/math-tutor' && Boolean(url.searchParams.get('session')) && url.searchParams.get('session') !== previous);
    await connected();
    assert.equal(await page.getByRole('textbox', { name: '聊天输入', exact: true }).inputValue(), '', 'New conversation must have an empty draft');
}

function lastEvent(events) {
    return [...events].reverse().find(e => e.direction === 'received' && ['assistant_complete', 'assistant_partial', 'tutor_message'].includes(e.frame?.event_type))?.frame;
}

async function turn(action) {
    const start = frames.length;
    await action();
    await until(() => frames.slice(start).some(row => row.direction === 'received' && ['turn_end', 'error'].includes(row.frame?.event_type)), 60000, 'real WebSocket turn end');
    const events = frames.slice(start);
    const error = events.find(e => ['error', 'assistant_error'].includes(e.frame?.event_type));
    assert(!error, JSON.stringify(error?.frame));
    assert(events.some(e => e.direction === 'sent'), 'No original client command was sent');
    assert(events.some(e => e.frame?.event_type === 'turn_end'), 'No completed product turn');
    const event = lastEvent(events);
    return {events, event, text: event?.payload?.final_text || event?.payload?.student_message || ''};
}

async function send(text) {
    await connected();
    const input = page.getByRole('textbox', { name: '聊天输入', exact: true });
    await input.fill(text);
    const result = await turn(() => page.getByRole('button', {name: /^(发送|提交本题步骤)$/, exact: true}).click());
    await until(async () => await input.inputValue() === '', 10000, 'actual successful send clears draft');
    return result;
}

async function command(name) {
    let button = page.getByRole('button', { name, exact: true });
    if (!await button.isVisible().catch(() => false)) {
        const opener = page.getByRole('button', { name: '当前教学支持与可用操作', exact: true });
        if (await opener.getAttribute('aria-pressed') !== 'true')
            await opener.click();
        button = page.getByRole('button', { name, exact: true });
    }
    assert(await button.isEnabled(), `Product action disabled: ${name}`);
    return turn(() => button.click());
}

async function closeTools() {
    const opener = page.getByRole('button', { name: '当前教学支持与可用操作', exact: true });
    if (await opener.count() && await opener.getAttribute('aria-pressed') === 'true')
        await opener.click();
}

async function attempt(answer) {
    await closeTools();
    const writeButton = page.getByRole('button', { name: '我来写', exact: true });
    if (await writeButton.isVisible().catch(() => false))
        await writeButton.click();
    assert(await page.getByRole('button', { name: '提交本题步骤', exact: true }).isVisible(), 'Must submit using the real attempt UI');
    return send(answer);
}

async function evidence() {
    return api('/desktop/student-evidence');
}

async function summary() {
    return api('/desktop/student-summary');
}

async function plan(goal) {
    if (goal)
        await api('/desktop/recommendations/configuration', { method: 'PUT', body: {
                enabled: false, goal, language: 'zh'
            } });
    return api('/desktop/recommendations');
}
const independentRows = value => (value.items || []).filter(row => row.evidence_kind === 'independent' && !row.excluded);
function verifiedProblem(result) {
    assert.equal(result.event?.payload?.status, 'COMPLETED', 'Mathematics turn did not finish completely');
    assert(result.event?.problem_context, 'No real problem context');
    assert(!/UNVERIFIED|CLARIFICATION|DISCUSSION/.test((result.event.cycle_state || '').toUpperCase()), 'Safe unsupported/clarification is not a completed supported mathematics case');
    assert.equal(String(result.event.problem_context.lifecycle).toUpperCase(), 'ACTIVE');
}

async function captureSurface(name) {
    write(`${name}-visible.json`, {at: stamp(), url: page.url(), body: await page.locator('body').innerText()});
    await page.screenshot({path: path.join(output, `${name}.png`), fullPage: true, animations: 'disabled'});
}

async function retryProfileRecommendation(pattern, caseId) {
    const retry = page.getByRole('button', {name: '重新加载学习推荐', exact: true});
    await retry.click({trial: true});
    await captureSurface(`${caseId}-visible-error`);
    await page.evaluate(() => {
        window.recommendationRetryClicked = false;
        document.addEventListener('click', function observe(event) {
            if (event.target.closest('button')?.textContent.trim() === '重新加载学习推荐') {
                window.recommendationRetryClicked = true;
                document.removeEventListener('click', observe, true);
            }
        }, true);
    });
    await page.route(pattern, async route => {
        if (await page.evaluate(() => window.recommendationRetryClicked)) return route.continue();
        return route.fallback();
    });
    await Promise.all([
        page.waitForResponse(response => response.url().includes('/recommendations/start?')
            && response.request().method() === 'POST' && response.ok()),
        retry.click(),
    ]);
    await retry.waitFor({state: 'hidden'});
    const expected = await plan();
    const section = page.getByRole('region', {name: '下一步学习资料', exact: true});
    await section.getByText(expected.plan.title, {exact: true}).waitFor();
    await captureSurface(`${caseId}-after-real-retry`);
}

async function closeApplication() {
    if (!application) return;
    const instance = application;
    const ownedProcess = instance.process();
    if (page && !page.isClosed()) {
        await captureSurface(`${currentCase || 'shutdown'}-before-quit`);
        const draft = page.getByRole('textbox', {name: /^(聊天输入|Chat input|你想弄清什么？)$/});
        if (await draft.isVisible().catch(() => false)) {
            const value = await draft.inputValue();
            if (value) {
                await draft.clear();
                requests.push({at: stamp(), case: currentCase, setup: 'Cleared disposable acceptance draft before normal quit', previous_draft: value});
            }
        }
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    }
    closing = true;
    let timeout;
    try {
        await Promise.race([
            instance.close(),
            new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('Normal installed application exit exceeded20seconds')), 20000); }),
        ]);
    } catch (error) {
        write(`${currentCase || 'shutdown'}-exit-failure.json`, {at: stamp(), pid: ownedProcess.pid,
            normal_exit: false, forced_cleanup: 'SIGKILL owned Electron process only', reason: error.message});
        ownedProcess.kill('SIGKILL');
        throw error;
    } finally {
        clearTimeout(timeout);
        const startupLog = path.join(data, 'logs', 'startup.log');
        if (fs.existsSync(startupLog)) fs.copyFileSync(startupLog, path.join(output, `startup-launch-${launches}.log`));
        closing = false;
        application = null;
    }
}

async function runCase(id, fn) {
    if (!chosen.includes(id))
        return;
    currentCase = id;
    const first = frames.length, req = requests.length, errorCount = errors.length, begin = Date.now();
    const row = resultFor(id);
    row.started_at = stamp();
    try {
        const observation = await fn();
        row.status = observation?.needs_review ? 'needs_review' : 'passed';
        row.observation = observation || {};
        delete row.reason;
    }
    catch (error) {
        row.status = 'failed';
        row.reason = error.message;
        row.error = error.stack;
    }
    finally {
        row.elapsed_seconds = (Date.now() - begin) / 1000;
        row.finished_at = stamp();
        try {
            if (page && !page.isClosed()) {
                write(`${id}-visible.json`, { url: page.url(), body: await page.locator('body').innerText() });
                await page.screenshot({ path: path.join(output, `${id}.png`), fullPage: true, animations: 'disabled' });
                row.screenshot = `${id}.png`;
            }
        }
        catch (error) {
            row.capture_error = error.message;
        }
        if (errors.length > errorCount) {
            row.status = 'failed';
            row.reason = 'Uncaught renderer error during actual installed case';
            row.renderer_errors = errors.slice(errorCount);
        }
        write(`${id}-protocol.json`, {
            case: row, frames: frames.slice(first), same_origin_api: requests.slice(req)
        });
        save();
        console.log(JSON.stringify({
            at: stamp(), case: id, status: row.status, seconds: row.elapsed_seconds, reason: row.reason
        }));
        currentCase = null;
    }
}

async function solve(id, question, answerPattern) {
    return runCase(id, async () => {
        await newChat();
        const initial = await send(question);
        verifiedProblem(initial);
        await command('提示');
        const full = await command('查看完整答案');
        assert(answerPattern.test(normalize(full.text)), `Expected mathematical result missing from actual solution: ${full.text}`);
        return {
            input: question,
            answer: full.text,
            cycle_id: initial.event.cycle_id,
            mode: 'actual_ui_and_real_ws',
            provider: 'unconfigured_template',
            needs_review: true,
            review_reason: 'Final-answer matching does not verify the displayed derivation. Independently check every step, relation sign, condition, and complete expression.'
        };
    });
}
try {
    save();
    await launch();
    await runCase('D01', async () => {
        const p = await plan();
        const s = await summary();
        assert.equal(p.plan.evidence_count, 0);
        assert.equal(s.has_independent_evidence, false);
        assert(!p.plan.evidence_ids.length);
        await goto('/math-tutor/profile');
        await page.getByRole('heading', { name: '学习画像', exact: true }).waitFor();
        return { plan: p, summary: s };
    });

    await runCase('L01', async () => {
        await goto('/math-tutor');
        const topControls = await page.locator('button,a,select').evaluateAll(elements => elements.filter(el => {
            const bounds = el.getBoundingClientRect();
            return bounds.width && bounds.height && bounds.top < 100 && bounds.left < 420
                && /^(中文|English|中|英|简体中文)$/.test(el.textContent.trim());
        }).map(el => ({tag: el.tagName, text: el.textContent})));
        assert.deepEqual(topControls, [], 'Duplicate top-left language control');
        const brand = page.getByRole('link', {name: /^MathTutor/}).first();
        const previousLocale = await page.locator('html').getAttribute('lang');
        if (await brand.count()) {
            await brand.click();
            await connected();
            assert.equal(await page.locator('html').getAttribute('lang'), previousLocale, 'Brand click changed language');
        }
        const layouts = [];
        try {
            for (const locale of ['zh-CN', 'en']) {
                await goto('/math-tutor/settings?section=general');
                await page.getByRole('combobox', {name: /^(界面语言|Interface language)$/}).selectOption(locale);
                for (const width of [1280, 960]) {
                    await application.evaluate(({BrowserWindow}, size) => {
                        BrowserWindow.getAllWindows()[0].setSize(size, 840);
                    }, width);
                    await goto('/math-tutor');
                    const home = await page.locator('body').innerText();
                    await page.screenshot({path: path.join(output, `L01-${locale}-${width}-home.png`), fullPage: true, animations: 'disabled'});
                    await goto('/math-tutor/profile');
                    const profileSection = page.getByRole('region', {name: /^(下一步学习资料|Resources for your next step)$/});
                    await profileSection.waitFor();
                    const profile = await page.locator('body').innerText();
                    await page.screenshot({path: path.join(output, `L01-${locale}-${width}-profile-overview.png`), fullPage: true, animations: 'disabled'});
                    await profileSection.scrollIntoViewIfNeeded();
                    await page.screenshot({path: path.join(output, `L01-${locale}-${width}-profile.png`), fullPage: true, animations: 'disabled'});
                    layouts.push({locale, native_window_width: width, viewport: await page.evaluate(() => ({width: innerWidth, height: innerHeight})),
                        empty_home_has_recommendations: /下一步学习资料|Resources for your next step/.test(home),
                        profile_has_recommendations: await profileSection.count() === 1,
                        home, profile});
                }
            }
        } finally {
            await application.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].setSize(1280, 840));
            await goto('/math-tutor/settings?section=general');
            await page.getByRole('combobox', {name: /^(界面语言|Interface language)$/}).selectOption('zh-CN');
        }
        write('L01-layouts.json', layouts);
        assert(layouts.every(view => !view.empty_home_has_recommendations), 'Empty tutoring home still contains next-learning-resources module');
        assert(layouts.every(view => view.profile_has_recommendations), 'Profile recommendation details missing in a locale or native narrow window');
        return {duplicate_top_left_controls: topControls, real_settings_roundtrip: true, layouts,
            scope_amendment: 'User requested homepage removal after coverage freeze; separate locale/native-window screenshots retained'};
    });

    await runCase('C01', async () => {
        await newChat();
        const started = await send('2x+3=7');
        verifiedProblem(started);
        const before = await evidence();
        const response = await attempt('x=2');
        const after = await evidence();
        const added = independentRows(after).filter(e => !independentRows(before).some(old => old.event_id === e.event_id));
        assert(added.some(e => e.correctness === 'correct'), 'No independent correct evidence for real submission');
        shared.independent = {
            session: started.event.payload?.conversation_id, cycle: started.event.cycle_id, problem: started.event.problem_context.display_text, before, after, added, response
        };
        return shared.independent;
    });
    await solve('A01', '3/4 + 1/8', /7\/8|0\.875/);
    await solve('A02', '化简 2(x+3)-x', /x\+6|6\+x/);
    await solve('A03', '2x+3=7', /x=2/);
    await solve('A04', '2x+3<7', /x<2|x∈-∞,2/);
    for (const [id, question, x, value] of [['A05', '画出函数 y=x^2', '0', '0'], ['A06', '画出函数 y=2x+1，读取 x=2 时的函数值', '2', '5']])
        await runCase(id, async () => {
            await newChat();
            const result = await send(question);
            const input = page.getByRole('spinbutton', {name: 'x 坐标', exact: true});
            await page.locator('canvas[role=img]').waitFor();
            if (await input.count()) {
                await input.fill(x);
                await input.press('Enter');
                const figure = input.locator('xpath=ancestor::figure');
                const table = await figure.getByRole('table').innerText();
                const rows = await figure.getByRole('row').allTextContents();
                assert(rows.some(row => row.includes(x) && row.includes(value)), `Expected graph reading (${x}, ${value})`);
                if (id === 'A05') {
                    await input.fill('5');
                    await figure.getByRole('button', {name: '读取', exact: true}).click();
                    const edgeTable = figure.getByRole('table', {name: 'x = 5 的函数读数', exact: true});
                    await edgeTable.waitFor();
                    const edgeValue = (await edgeTable.getByRole('cell').innerText()).trim();
                    const readouts = {
                        question, origin_table: table, edge_table: await edgeTable.innerText(),
                        edge_x: 5, actual_edge_y: edgeValue, expected_edge_y: 25,
                        interaction: 'Actual installed input and Read button; same graph after x=0',
                        coverage_added: 'Post-observation regression for values beyond the drawing viewport'
                    };
                    write('A05-readouts.json', readouts);
                    assert.equal(edgeValue, '25', 'Expected y=x² at x=5 to read 25; drawing bounds must not clip mathematical values');
                    return {question, table, readouts, reply: result.text, actual_renderer: 'function readout'};
                }
                return {question, table, reply: result.text, actual_renderer: 'function readout'};
            }
            const sceneMatch = result.text.match(/```mathtutor-scene\n([\s\S]*?)\n```/);
            assert(sceneMatch, 'No actual function readout or combined geometry scene');
            const scene = JSON.parse(sceneMatch[1]);
            const mark = scene.marks.find(point => point.x === Number(x) && point.y === Number(value));
            assert(mark, `Combined scene omits expected (${x}, ${value})`);
            await page.getByText(mark.label, {exact: false}).first().waitFor();
            return {question, visible_mark: mark, scene, reply: result.text, actual_renderer: 'combined scene marked intersection'};
        });
    await solve('A07', '3(x-2)+5=2x+8', /x=9/);
    await runCase('A08', async () => {
        await newChat();
        const before = await evidence();
        const response = await send('(x^2-1)/(x-1)=2，且 x≠1');
        assert.equal(response.event?.payload?.status, 'COMPLETED');
        assert(/无解/.test(response.text), 'No complete mathematical conclusion');
        assert(/\\ne(?:q)?\s*1|≠\s*1/.test(response.text), 'Excluded denominator value missing');
        assert(/分母为零，舍去|分母[^。\n]*零[^。\n]*舍去/.test(response.text), 'Candidate root not excluded with its reason');
        const after = await evidence();
        assert.equal(independentRows(after).length, independentRows(before).length);
        return {reply: response.text, session: response.event.payload.conversation_id,
            actual_mode: 'bounded rational-equation response; not general interactive tutoring',
            needs_review: true, review_reason: 'Independently verify complete math and durable formula_receipt from retained synthetic database'};
    });
    for (const id of ['B01', 'B02', 'B03', 'B04', 'B05'])
        await runCase(id, async () => {
            await newChat();
            const before = await evidence();
            const result = await send(resultFor(id).stimulus);
            assert(!/AWAITING_ATTEMPT|AWAITING_SUBGOAL/.test((result.event?.cycle_state || '').toUpperCase()), 'Unreliable or open question entered verified attempt route');
            assert(result.text.trim().length > 5, 'Missing bounded response');
            const after = await evidence();
            assert.equal(independentRows(after).length, independentRows(before).length, 'Question created independent mastery evidence');
            return {
                reply: result.text, state: result.event?.cycle_state, needs_review: true, review_reason: 'Independent reviewer must confirm substantive boundary/clarification wording, not only route state'
            };
        });

    await runCase('C02', async () => {
        await newChat();
        const initial = await send('3x-4=8');
        verifiedProblem(initial);
        shared.help = { initial, before: await evidence() };
        const hint = await command('提示');
        shared.help.first = hint;
        assert((hint.event?.payload?.effective_assistance_level ?? 0) > 0, 'First hint exposure missing');
        return { hint, independent_records_before: independentRows(shared.help.before).length };
    });

    await runCase('C03', async () => {
        assert(shared.help?.first, 'First hint setup did not succeed');
        const hint = await command('提示');
        assert((hint.event?.payload?.effective_assistance_level ?? 0) > (shared.help.first.event?.payload?.effective_assistance_level ?? 0), 'Second hint did not progress beyond first-level support');
        assert.notEqual(normalize(hint.text), normalize(shared.help.first.text), 'Second hint repeated identical support');
        shared.help.second = hint;
        return {
            hint, needs_review: true, review_reason: 'Check second-stage teaching content and mathematics against first hint'
        };
    });

    await runCase('C04', async () => {
        assert(shared.help?.first, 'Hint setup did not succeed');
        const full = await command('查看完整答案');
        assert(/x=4/.test(normalize(full.text)));
        const afterView = await evidence();
        const originalCount = independentRows(shared.help.before).length;
        assert.equal(independentRows(afterView).length, originalCount, 'Viewing hints/answer created independent evidence');
        const copied = await attempt('x=4');
        const afterCopy = await evidence();
        const rows = afterCopy.items.filter(row => !afterView.items.some(old => old.event_id === row.event_id));
        assert(rows.some(row => row.correctness === 'correct' && row.evidence_kind === 'post_solution'), 'Copying a shown answer was not recorded as post-solution work');
        assert.equal(independentRows(afterCopy).length, originalCount, 'Copying a shown answer created independent evidence');
        return {full, after_view: afterView, copied, post_solution_records: rows, after_copy: afterCopy};
    });

    await runCase('C05', async () => {
        await newChat();
        const initial = await send('4x-5=7');
        verifiedProblem(initial);
        const wrong = await attempt('x=2');
        const wrongEvidence = await evidence();
        shared.wrongPlan = await plan('linear_isolation');
        const right = await attempt('x=3');
        const after = await evidence();
        assert((wrongEvidence.items || []).some(e => e.cycle_id === initial.event.cycle_id && e.correctness === 'incorrect'), 'Incorrect attempt not preserved');
        assert((after.items || []).some(e => e.cycle_id === initial.event.cycle_id && e.correctness === 'correct'), 'Correction not preserved');
        shared.corrected = {
            cycle: initial.event.cycle_id, wrong, right, after
        };
        return shared.corrected;
    });

    await runCase('C06', async () => {
        assert(shared.independent?.session, 'Independent completion setup unavailable');
        await goto('/math-tutor?session=' + encodeURIComponent(shared.independent.session));
        await connected();
        const acceptExisting = page.getByRole('button', { name: '开始这道练习', exact: true });
        const hasExisting = await acceptExisting.isVisible().catch(() => false);
        const offer = hasExisting ? { existing_offer_observed: true } : await command('再来一道');
        const accepted = await command('开始这道练习');
        assert(accepted.event?.cycle_id && accepted.event.cycle_id !== shared.independent.cycle, 'Practice did not create a fresh cycle');
        assert.notEqual(normalize(accepted.event.problem_context.display_text), normalize(shared.independent.problem), 'Practice repeated the already completed problem');
        shared.transfer = {
            old_cycle: shared.independent.cycle, new_cycle: accepted.event.cycle_id, offer, accepted
        };
        return { ...shared.transfer, scope: 'Fresh follow-up exercise; no delayed-retention or structural-transfer outcome is inferred' };
    });

    await runCase('C07', async () => {
        assert(shared.independent, 'Independent evidence setup unavailable');
        const before = await evidence();
        await goto('/math-tutor/profile');
        await page.getByRole('heading', { name: '学习画像', exact: true }).waitFor();
        const profile = await summary();
        const skill = profile.skills.find(s => s.code === 'linear_isolation');
        assert(skill, 'No linear skill projection');
        await page.locator('article').filter({ has: page.getByText(skill.label, { exact: true }) }).filter({ has: page.getByRole('button', { name: '查看依据', exact: true }) }).getByRole('button', { name: '查看依据', exact: true }).click();
        await page.getByRole('dialog').waitFor();
        await until(async () => /你的作答/.test(await page.getByRole('dialog').innerText()), 10000, 'actual evidence drawer rows');
        const dialog = await page.getByRole('dialog').innerText();
        const after = await evidence();
        assert.equal(independentRows(after).length, independentRows(before).length, 'Viewing evidence added independent records');
        assert(/2x|4x|7/.test(dialog));
        await page.keyboard.press('Escape');
        return { dialog, summary: await summary() };
    });

    await runCase('D02', async () => {
        await goto('/math-tutor/profile');
        assert(shared.independent, 'Independent evidence unavailable');
        const p = await plan('linear_isolation');
        assert(p.plan.last_event_seq > 0, 'Planner ignores real recorded events');
        assert(p.plan.profile_revision);
        const knownAttemptIds = new Set((shared.corrected?.after.items || shared.independent.after.items).map(item => item.event_id));
        assert(p.plan.evidence_ids.some(id => knownAttemptIds.has(id)), 'Plan does not cite an actual submitted response');
        return {
            plan: p, needs_review: true, review_reason: 'Judge target/action against actual submitted evidence'
        };
    });

    await runCase('D03', async () => {
        await goto('/math-tutor/profile');
        assert(shared.transfer, 'Actual fresh follow-up unavailable');
        assert.notEqual(shared.transfer.new_cycle, shared.transfer.old_cycle);
        return {
            completed_cycle: shared.transfer.old_cycle, next_cycle: shared.transfer.new_cycle, plan: await plan(), needs_review: true, review_reason: 'Completed task is freshened; skill mastery must still be independently assessed'
        };
    });

    await runCase('D04', async () => {
        await goto('/math-tutor/profile');
        assert(shared.wrongPlan, 'Actual wrong-answer state unavailable');
        return {
            plan_after_real_error: shared.wrongPlan, needs_review: true, review_reason: 'Check prerequisite and progression appropriateness without inferring a localized weakness from a whole-problem error'
        };
    });

    await runCase('D05', async () => {
        await goto('/math-tutor/settings?section=sources');
        const section = page.locator('section[aria-labelledby="discovery-settings-title"]');
        await section.getByRole('combobox').selectOption('probability');
        await until(async () => (await plan()).goal === 'probability');
        const p = await plan();
        assert.equal(p.enabled, false);
        assert.equal(p.goal, 'probability');
        assert.equal(p.plan.goal, p.goal, 'Plan contradicts configured goal');
        shared.goal = p.goal;
        return { plan: p };
    });

    await runCase('D06', async () => {
        await plan('probability');
        const configuration = await api('/desktop/exploration/configuration');
        assert.equal(configuration.configured, false, 'Real Zhihu credentials exist; only the parent live-provider run may execute this case');
        await newChat();
        await page.getByRole('button', { name: '联网', exact: true }).click();
        const result = await send('我现在想学线性代数，请给出适合入门的下一步。');
        const session = result.event?.payload?.conversation_id;
        assert(session, 'Missing real session');
        const persisted = await api('/sessions/' + encodeURIComponent(session));
        const message = [...(persisted.messages || [])].reverse().find(m => m.role === 'tutor');
        let context = message?.continuation_context;
        if (typeof context === 'string') {
            try {
                context = JSON.parse(context);
            }
            catch {
            }
        }
        const receipt = context?.network_evidence?.planner;
        return {
            reply: result.text, persisted, receipt, receipt_available_in_public_api: Boolean(receipt), durable_receipt_review: 'Read-only retained synthetic database after shutdown', needs_review: true, review_reason: 'Confirm current explicit request takes priority and generated/local next steps agree; no provider calls are made'
        };
    });

    await runCase('F01', async () => {
        await goto('/math-tutor/profile');
        let transportFailed = false;
        try {
            await page.context().setOffline(true);
            transportFailed = await page.evaluate(async () => {
                try { await fetch('/api/v2/math-tutor/desktop/recommendations'); return false; }
                catch { return true; }
            });
            assert(transportFailed, 'Offline injection did not fail an actual same-origin profile request');
            await page.screenshot({path: path.join(output, 'F01-profile-offline.png'), fullPage: true, animations: 'disabled'});
        } finally {
            await page.context().setOffline(false);
        }
        await goto('/math-tutor/profile');
        await page.getByRole('heading', {name: '学习画像', exact: true}).waitFor();
        await newChat();
        const input = page.getByRole('textbox', {name: '聊天输入', exact: true});
        await input.fill('离线草稿：2x+3=7');
        try {
            await page.context().setOffline(true);
            await delay(1000);
            assert.equal(await input.inputValue(), '离线草稿：2x+3=7');
        } finally {
            await page.context().setOffline(false);
        }
        await connected();
        assert.equal(await input.inputValue(), '离线草稿：2x+3=7');
        await input.clear();
        return {injection: 'Chromium HTTP transport offline/online; existing WebSocket not forcibly closed',
            entry: 'Learning profile', actual_same_origin_request_failed: transportFailed, profile_restored: true, draft_preserved: true};
    });

    await runCase('F02', async () => {
        const pattern = '**/recommendations/start?*';
        const held = [];
        await page.route(pattern, route => held.push(route));
        try {
            await goto('/math-tutor/profile');
            await until(() => held.length > 0, 15000, 'profile recommendation request');
            await page.getByRole('heading', {name: '学习画像', exact: true}).waitFor();
            await page.screenshot({path: path.join(output, 'F02-profile-pending.png'), fullPage: true, animations: 'disabled'});
            for (const route of held) await route.abort('timedout').catch(() => {});
            await until(async () => /学习推荐暂时无法更新|重新加载学习推荐|稍后再试|重试/.test(await page.locator('body').innerText()), 10000, 'visible bounded timeout recovery');
            await retryProfileRecommendation(pattern, 'F02');
            await newChat();
            const input = page.getByRole('textbox', {name: '聊天输入', exact: true});
            await input.fill('推荐超时后仍可输入');
            assert.equal(await input.inputValue(), '推荐超时后仍可输入');
            await input.clear();
            return {injection: 'Browser-side profile recommendation response timedout; not a provider timeout',
                intercepted: held.length, chat_interactive_after_failure: true, actual_retry_button_recovered: true, needs_review: true,
                review_reason: 'Independently inspect captured timeout wording and profile recovery'};
        } finally {
            write('F02-injection.json', {kind: 'renderer HTTP timedout', intercepted: held.length, provider_calls: 0});
            await captureSurface('F02-before-recovery');
            for (const route of held) await route.abort('timedout').catch(() => {});
            await page.unroute(pattern);
            await goto('/math-tutor/profile');
        }
    });

    await runCase('F03', async () => {
        const pattern = '**/recommendations/start?*';
        let requestsSeen = 0;
        await page.route(pattern, async route => {
            requestsSeen++;
            await route.fulfill({status: 429, contentType: 'application/json',
                body: JSON.stringify({detail: 'Installed acceptance injected rate limit'})});
        });
        try {
            await goto('/math-tutor/profile');
            await until(() => requestsSeen > 0, 15000, 'profile injected rate-limit request');
            await until(async () => /学习推荐暂时无法更新|重新加载学习推荐|稍后再试|重试/.test(await page.locator('body').innerText()), 10000, 'visible rate-limit recovery');
            assert(requestsSeen < 6, 'Unbounded recommendation retry burst');
            await retryProfileRecommendation(pattern, 'F03');
            return {injection: 'Browser-side HTTP429 on profile recommendations, not real provider limit',
                requests: requestsSeen, actual_retry_button_recovered: true, needs_review: true, review_reason: 'Check rate-limit retry wording from actual profile UI'};
        } finally {
            write('F03-injection.json', {kind: 'renderer HTTP429', intercepted: requestsSeen, provider_calls: 0});
            await captureSurface('F03-before-recovery');
            await page.unroute(pattern);
            await goto('/math-tutor/profile');
        }
    });

    await runCase('F04', async () => {
        await newChat();
        const settings = await api('/desktop/settings');
        assert.equal(settings.is_configured, false);
        const result = await send('2x+3=7');
        verifiedProblem(result);
        return {
            actual_missing_provider_configuration: true, deterministic_tutoring_available: true, reply: result.text
        };
    });

    await runCase('F06', async () => {
        await newChat();
        verifiedProblem(await send('2x+3=7'));
        const input = page.getByRole('textbox', {name: '聊天输入', exact: true});
        const preservedDraft = '取消退出后保留的草稿';
        await input.fill(preservedDraft);
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const previousDialogs = requests.filter(item => item.native_dialog).length;
        await application.evaluate(({app}) => { app.quit(); });
        await until(() => requests.filter(item => item.native_dialog).length > previousDialogs, 10000, 'native quit confirmation');
        assert.equal(await input.inputValue(), preservedDraft, 'Cancelling quit lost the draft');
        assert.equal(application.process().exitCode, null, 'Cancelling quit terminated the installed application');
        const availableAfterCancel = await summary();
        await captureSurface('F06-cancelled-quit');
        await input.clear();
        const continued = await command('提示');
        assert(continued.text, 'No actual WebSocket response after cancelled quit');
        const delivery = continued.event.delivery_id;
        assert(delivery, 'The hint must have a presentation receipt');
        const database = new DatabaseSync(path.join(data, 'math_tutor.db'), {readOnly: true});
        let presented;
        try {
            const lookup = database.prepare('SELECT event_seq FROM learning_events WHERE event_id = ? AND event_type = ?');
            await until(() => (presented = lookup.get(delivery + ':help_presented', 'help_presented')), 15000, 'the visible hint to be saved');
        } finally {
            database.close();
        }
        await until(async () => (await summary()).last_event_seq >= presented.event_seq, 10000, 'the learner profile to include that hint');
        const before = await summary();
        const p = await plan();
        const sessions = await api('/sessions');
        await closeApplication();
        await launch();
        const after = await summary();
        const later = await plan();
        const reloaded = await api('/sessions');
        assert.deepEqual(after, before, 'Restart changed saved learner summary');
        assert.equal(later.goal, p.goal);
        assert.equal(later.plan.last_event_seq, p.plan.last_event_seq);
        assert.equal(reloaded.length, sessions.length);
        return {normal_installed_relaunch: true, cancelled_quit_kept_service_and_draft: true,
            service_after_cancel: availableAfterCancel, real_ws_after_cancel: continued,
            summary: after, goal: later.goal, session_count: reloaded.length};
    });

    await runCase('F07', async () => {
        if (!application) await launch();
        await goto('/math-tutor/settings?section=advanced');
        const original = await plan('probability');
        const snapshot = await summary();
        const backup = await api('/desktop/backup', { method: 'POST' });
        assert(backup.ok && backup.backup?.path);
        const verify = await api('/desktop/backup/verify', { method: 'POST', body: { path: backup.backup.path } });
        await plan('linear_algebra');
        assert.equal((await plan()).goal, 'linear_algebra');
        const restore = await api('/desktop/backup/restore', { method: 'POST', body: { path: backup.backup.path } });
        assert(restore.ok, `Actual restore rejected: ${restore.message}`);
        if (restore.restart_required) {
            await closeApplication();
            await launch();
        } else {
            await goto('/math-tutor');
        }
        const p = await plan();
        assert.equal(p.goal, original.goal, 'Backup did not restore recommendation goal');
        assert.deepEqual(await summary(), snapshot, 'Backup did not restore learner summary');
        return {
            mode: 'Real installed service backup/verify/restore through normal same-origin API', backup, verify, restore, restored_goal: p.goal
        };
    });
}
catch (error) {
    write('driver-failure.json', {
        at: stamp(), message: error.message, stack: error.stack
    });
    for (const row of results)
        if (chosen.includes(row.id) && row.status === 'not_run')
            row.reason = 'Driver blocked before case: ' + error.message;
    process.exitCode = 1;
}
finally {
    if (application)
        await closeApplication().catch(error => errors.push({at: stamp(), message: error.message}));
    const startupLog = path.join(data, 'logs', 'startup.log');
    if (fs.existsSync(startupLog))
        fs.copyFileSync(startupLog, path.join(output, 'startup.log'));
    write('navigation.json', navigation);
    write('protocol-frames.json', frames);
    write('same-origin-requests.json', requests);
    save();
    if (results.some(r => chosen.includes(r.id) && r.status === 'failed') || errors.length)
        process.exitCode = 1;
    console.log(JSON.stringify({
        at: stamp(), output, automatic_failures: results.filter(r => r.status === 'failed').length, overall_product_acceptance: 'See installed-product-acceptance.json; unrun/manual/provider checks are not passes'
    }));
}

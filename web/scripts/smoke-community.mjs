// Real rendered UI, synthetic mutable HTTP fixtures. Backend parsing, owner
// isolation, permissions and workflows are independently tested in Python.
// No public catalog, student account, model or paid provider is contacted.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.LAYOUT_URL || 'http://localhost:3198';
const output = await mkdtemp(path.join(tmpdir(), 'mathtutor-community-'));
const browser = await chromium.launch({executablePath: process.env.CHROME_EXECUTABLE, headless: true});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
page.setDefaultTimeout(15000); await page.emulateMedia({reducedMotion: 'reduce'});
const errors = [], mutations = [], screenshots = [], calls = [];
page.on('pageerror', error => errors.push(error.message));
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const stamp = '2026-10-16T08:00:00Z';
const library = {space_id: 'fixture-library', name: '我的数学资料', kind: 'course', conversation_id: '', enabled: 1};
const workflows = ['exam-builder', 'mistake-review', 'learning-report'];
const names = ['智能组卷', '错题整理', '学习趋势'];
const ids = ['fixture.exam', 'fixture.mistakes', 'fixture.report'];
const defaults = [{grade: 10, question_count: 8, seed: 42, point_codes: [], include_answers: true, focus_weak_skills: false}, {limit: 12, include_assisted: true, include_partial: true}, {window_size: 10, max_events: 500}];
const packages = workflows.map((workflow, index) => ({schema_version: 'mathtutor.community-plugin.v1', kind: 'teaching-plugin', id: ids[index], version: '1.0.0', name: names[index], author: '夹具作者', license: 'MIT', description: `仅用于界面验收的${names[index]}插件。`, tags: ['界面夹具'], grades: [10, 11, 12], readme: '# 插件说明\n基于实际可用资料运行。', changelog: '首次发布', workflow, defaults: defaults[index], teaching_guidance: '结合实际证据指导练习。', required_permissions: [index === 0 ? 'question_bank' : 'read_learning_records']}));
const builtin = {id: 'builtin', name: '项目示例', kind: 'builtin', source_url: null, sha256: hash('catalog'), last_refreshed: null, error: null, stale: false, resource_count: 4};
let sources = [builtin], reportHasData = false, refreshCount = 0, pluginFailure = false;
const installed = new Map(), favorites = new Set(), imports = new Map();
const question = {id: 'fixture.equations', version: '1.0.0', type: 'question-pack', name: '共享方程题库', author: '夹具作者', license: 'CC-BY-4.0', description: '一元一次方程练习与可编辑参考解答。', tags: ['方程', '界面夹具'], grades: [7], readme: '# 使用说明\n先尝试，再核对参考答案。', changelog: '补充方程练习', permissions: [], package_sha256: hash('questions'), package_size_bytes: 1200, project_example: true, source_id: 'builtin', source_name: '项目示例', importable: true, plugin_id: null, project_url: 'https://github.com/example/math', issues_url: 'https://github.com/example/math/issues', discussions_url: 'javascript:alert(1)', source_url: null};
const resources = () => [question, ...packages.map(pkg => ({...question, ...pkg, type: 'plugin', plugin_id: pkg.id, permissions: pkg.required_permissions, package_sha256: hash(pkg), package_size_bytes: JSON.stringify(pkg).length, grades: pkg.grades}))].map(resource => {
  const record = installed.get(resource.id), versions = imports.get(resource.id) || [];
  return {...resource, favorite: favorites.has(resource.id), imported_versions: versions, latest_imported_version: versions.at(-1) || record?.plugin.version || null, update_status: record ? record.plugin.version === resource.version && record.package_hash === resource.package_sha256 ? 'current' : 'update_available' : versions.includes(resource.version) ? 'current' : 'not_imported'};
});
const detail = resource => ({...resource, preview: {available: true, partial: false, documents: resource.type === 'question-pack' ? [{path: '七年级/方程.md', title: '方程练习', body: '解方程：$2x+1=7$。\n参考答案：$x=3$。'}] : []}});
const install = pkg => {
  const old = installed.get(pkg.id), packageHash = hash(pkg);
  if (old?.package_hash === packageHash) return old;
  const row = {plugin: structuredClone(pkg), config: old?.config || structuredClone(pkg.defaults), enabled: false, consented_permissions: [], package_hash: packageHash, installed_at: old?.installed_at || stamp, updated_at: stamp}; installed.set(pkg.id, row); return row;
};
const result = record => {
  const common = {schema_version: 'mathtutor.community-result.v1', plugin_id: record.plugin.id, plugin_version: record.plugin.version, workflow: record.plugin.workflow, status: 'ok', read_only: true, authority: 'reference_only', config: record.config, teaching_guidance: record.plugin.teaching_guidance, limitations: ['只统计实际记录，不能据此认定全部知识掌握情况。']};
  if (record.plugin.workflow === 'exam-builder') return {...common, data: {title: '本次练习', questions: [{id: 'q1', text: '解方程 $2x+1=7$。', point_code: 'equation', point_title: '一元一次方程', grade: 10, difficulty: 1, reference_answer: 'x=3', explanation: '两边先减1，再除以2。'}, {id: 'q2', text: '求函数 $y=x^2$ 在 $x=2$ 时的值。', point_code: 'function', point_title: '函数', grade: 10, difficulty: 1, reference_answer: '4'}], requested_count: record.config.question_count, actual_count: 2, seed: record.config.seed, answers_included: record.config.include_answers}};
  if (record.plugin.workflow === 'mistake-review') return {...common, data: {assessed_count: 3, review_count: 1, self_report_count: 0, items: [{event_id: 'e1', occurred_at: stamp, correctness: 'incorrect', evidence_kind: 'independent', completion_scope: 'full_problem', skill_ids: ['equation'], problem_text: '解方程 2x+1=7', student_response: 'x=4', next_step: '先检查移项时常数项的符号。', assessment_id: 'a1'}]}};
  return {...common, status: reportHasData ? 'ok' : 'empty', data: {summary: {assessed_attempts: reportHasData ? 12 : 0, independent_attempts: reportHasData ? 12 : 0, independent_correct: reportHasData ? 6 : 0, independent_accuracy: reportHasData ? .5 : null, assisted_attempts: 0, post_solution_attempts: 0, self_report_count: 0}, trend: reportHasData ? [.25, .5, .75].map((accuracy, index) => ({index: index + 1, start_event_seq: index * 4 + 1, end_event_seq: index * 4 + 4, attempts: 4, correct: accuracy * 4, accuracy, first_at: stamp, last_at: stamp})) : [], skills: [], window: {max_events: 500, included_events: reportHasData ? 12 : 0, truncated: false}}};
};
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method();
  const tail = pathname.split('/community')[1]; calls.push({path: pathname, method}); let body = [];
  const json = () => request.postDataJSON();
  const download = value => route.fulfill({contentType: 'application/json', body: JSON.stringify(value, null, 2), headers: {'Content-Disposition': 'attachment; filename="fixture.json"'}});
  if (pathname.endsWith('/auth/status')) body = {enabled: false, authenticated: true};
  else if (pathname.endsWith('/bootstrap')) body = {phase: 'READY', readiness: 'READY', steps: []};
  else if (pathname.endsWith('/settings')) body = {is_configured: true, onboarding_completed: true, preset_id: 'local', model: 'fixture', base_url: 'http://127.0.0.1', key_masked: null, provider_configs: {}};
  else if (pathname.endsWith('/knowledge/libraries')) body = [library];
  else if (tail?.startsWith('/catalog')) {
    let rows = resources(); const q = url.searchParams.get('q'), type = url.searchParams.get('type'), stage = url.searchParams.get('stage');
    if (q) rows = rows.filter(row => [row.name, row.description, ...row.tags].join(' ').includes(q));
    if (type) rows = rows.filter(row => row.type === type);
    if (stage) rows = rows.filter(row => row.grades.some(grade => stage === 'primary' ? grade <= 6 : stage === 'middle' ? grade >= 7 && grade <= 9 : grade >= 10));
    if (url.searchParams.get('favorites_only') === 'true') rows = rows.filter(row => row.favorite);
    body = {resources: rows, sources, notice: '这些是明确标注的项目示例，没有公开下载量或评分。'};
  } else if (tail === '/plugins/examples') body = {items: packages};
  else if (tail === '/plugins/validate') { const pkg = json().package; assert.equal(pkg.kind, 'teaching-plugin'); assert.ok(pkg.id && pkg.readme); assert.ok(pkg.required_permissions.length); mutations.push({kind: 'validate', package: pkg}); body = {package: pkg, package_hash: hash(pkg)}; }
  else if (tail === '/import') {
    const multipart = request.postDataBuffer().toString('utf8'), content = /\r\n\r\n([\s\S]*?)\r\n--/.exec(multipart)?.[1]; assert.ok(content, 'file is uploaded directly'); assert.match(multipart, /name="operation_id"/);
    const input = JSON.parse(content); mutations.push({kind: 'direct-file-import', format: input.format || input.schema_version});
    if (input.schema_version === 'mathtutor.community-plugin.v1') body = {kind: 'plugin', plugin: install(input), warnings: []};
    else if (input.format === 'mathtutor.community-resource.v1' && input.resource.package?.data.schema_version === 'mathtutor.community-plugin.v1') body = {kind: 'plugin', plugin: install(input.resource.package.data), warnings: []};
    else if (input.format === 'mathtutor.community-resource.v1' || input.format === 'mathtutor.question-pack.v1') body = {kind: 'question-pack', space_id: 'file-imported-library', name: '直接导入的题库', imported_count: 1, warnings: []};
    else { const source = {id: 'imported-fixture', name: '手动导入目录', kind: 'imported', source_url: null, sha256: hash('import'), last_refreshed: stamp, error: null, stale: false, resource_count: 1}; sources.push(source); body = {kind: 'source', source, warnings: []}; }
  }
  else if (tail === '/plugins') {
    if (method === 'POST') { body = install(json().package); mutations.push({kind: 'raw-plugin-import', id: body.plugin.id}); }
    else if (pluginFailure) return route.fulfill({status: 503, json: {detail: '插件服务暂时不可用（验收夹具）'}});
    else body = {items: [...installed.values()]};
  } else if (/^\/plugins\/[^/]+\/(enabled|config|run|export)$/.test(tail || '')) {
    const [, , id, operation] = tail.split('/'), record = installed.get(decodeURIComponent(id)); assert.ok(record);
    if (operation === 'enabled') { const input = json(); if (input.enabled) assert.ok(record.plugin.required_permissions.every(permission => input.consent_permissions.includes(permission)), 'permission confirmation must be complete'); record.enabled = input.enabled; record.consented_permissions = input.enabled ? input.consent_permissions : []; mutations.push({kind: 'enable', id, ...input}); body = record; }
    else if (operation === 'config') { record.config = json().config; mutations.push({kind: 'config', id, config: record.config}); body = record; }
    else if (operation === 'run') { assert.equal(record.enabled, true); mutations.push({kind: 'run', id}); body = result(record); }
    else return download(record.plugin);
  } else if (/^\/plugins\/[^/]+$/.test(tail || '') && method === 'DELETE') { const id = decodeURIComponent(tail.split('/').at(-1)); installed.delete(id); mutations.push({kind: 'uninstall', id}); body = {plugin_id: id, uninstalled: true}; }
  else if (/^\/resources\/[^/]+(\/favorite|\/import|\/export)?$/.test(tail || '')) {
    const [, , id, operation] = tail.split('/'), resource = resources().find(row => row.id === decodeURIComponent(id)); assert.ok(resource);
    if (operation === 'favorite') { const {favorite} = json(); if (favorite) favorites.add(resource.id); else favorites.delete(resource.id); mutations.push({kind: 'favorite', id: resource.id, favorite}); body = detail({...resource, favorite}); }
    else if (operation === 'import') { const input = json(); assert.equal(input.version, resource.version); assert.equal(input.expected_sha256, resource.package_sha256); assert.match(input.operation_id, /^[0-9a-f-]{36}$/); mutations.push({kind: 'resource-import', id, ...input}); imports.set(resource.id, [...new Set([...(imports.get(resource.id) || []), resource.version])]); body = resource.type === 'plugin' ? {resource_id: id, version: resource.version, plugin: install(packages.find(pkg => pkg.id === id))} : {resource_id: id, version: resource.version, space_id: 'imported-library', name: resource.name, imported_count: 1, warnings: []}; }
    else if (operation === 'export') { assert.equal(url.searchParams.get('version'), resource.version); assert.equal(url.searchParams.get('expected_sha256'), resource.package_sha256); mutations.push({kind: 'resource-export', id}); return download({format: 'mathtutor.community-resource.v1', resource: {metadata: resource, package: {filename: 'fixture.mathtutor', media_type: 'application/json', data: resource.type === 'plugin' ? packages.find(pkg => pkg.id === resource.id) : {format: 'mathtutor.question-pack.v1', questions: [{id: 'q1', stem: '2x+1=7', answer: 'x=3'}]}}}}); }
    else { assert.equal(url.searchParams.get('version'), resource.version); body = detail(resource); }
  } else if (tail === '/sources' && method === 'POST') { const input = json(); body = {id: 'remote-fixture', name: input.name, kind: 'remote', source_url: input.url, sha256: null, last_refreshed: null, error: null, stale: true, resource_count: 0}; sources.push(body); mutations.push({kind: 'source-add', ...input}); }
  else if (tail === '/sources/import') { assert.match(request.postDataBuffer().toString('utf8'), /mathtutor\.community-resource\.v1/); body = {id: 'imported-fixture', name: '手动导入目录', kind: 'imported', source_url: null, sha256: hash('import'), last_refreshed: stamp, error: null, stale: false, resource_count: 1}; sources.push(body); mutations.push({kind: 'source-import'}); }
  else if (/^\/sources\/[^/]+\/refresh$/.test(tail || '')) { refreshCount++; const source = sources.find(row => row.id === tail.split('/')[2]); assert.ok(source); Object.assign(source, {stale: true, error: '目录暂时不可达（验收夹具）'}); mutations.push({kind: 'source-refresh'}); body = source; }
  else if (/^\/sources\/[^/]+$/.test(tail || '') && method === 'DELETE') { sources = sources.filter(source => source.id !== tail.split('/')[2]); body = {deleted: true}; mutations.push({kind: 'source-remove'}); }
  else if (/^\/libraries\/[^/]+\/publish$/.test(tail || '')) { assert.equal(tail.split('/')[2], library.space_id); const metadata = json(); assert.equal(metadata.project_url, 'https://github.com/creator/math'); mutations.push({kind: 'publish-download', metadata}); return download({format: 'mathtutor.community-resource.v1', resource: {...metadata, documents: [{path: '练习.md', body: '保存的实际正文夹具'}]}}); }
  else if (tail) throw new Error(`Unhandled community fixture: ${method} ${tail}`);
  await route.fulfill({json: body});
});
await page.routeWebSocket('**/api/**', () => {});
const tab = name => name === '社区来源' ? page.getByRole('button', {name: '社区来源（进阶）', exact: true}) : page.getByRole('navigation', {name: '社区内容'}).getByRole('button', {name, exact: true});
const open = async name => { await tab('发现资源').click(); await page.getByRole('button', {name, exact: true}).click(); await page.getByRole('region', {name: '资源详情'}).getByRole('heading', {name, exact: true}).waitFor(); await page.getByRole('region', {name: '资源详情'}).getByRole('button', {name: /^(导入|更新|再次导入)$/}).waitFor(); };
const card = name => page.locator('.community-plugin').filter({has: page.getByRole('heading', {name, exact: true})});
const installResource = async name => { await open(name); await page.getByRole('region', {name: '资源详情'}).getByRole('button', {name: /^(导入|更新|再次导入)$/}).click(); await page.getByRole('status').filter({hasText: /插件已导入|题库已添加/}).waitFor(); };
const enable = async name => { const item = card(name); await item.getByText('已停用', {exact: true}).waitFor(); await item.getByRole('button', {name: '同意并启用', exact: true}).click(); await item.getByText('已启用', {exact: true}).waitFor(); };

const capture = async name => { assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${name}: document cannot overflow horizontally`); await page.screenshot({path: path.join(output, `${name}.png`), animations: 'disabled'}); screenshots.push({name, viewport: page.viewportSize()}); };
const downloadWith = async (button, filename) => { const pending = page.waitForEvent('download'); await button.click(); const file = await pending, saved = path.join(output, filename); await file.saveAs(saved); return JSON.parse(await readFile(saved, 'utf8')); };
const uploadFile = async value => { const pending = page.waitForEvent('filechooser'); await page.getByRole('button', {name: '导入下载的插件/资源', exact: true}).click(); await (await pending).setFiles({name: 'fixture.mathtutor', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value))}); };
try {
  await page.goto(`${base}/math-tutor/community?tab=plugins`); await page.getByRole('heading', {name: '我的工具插件', exact: true}).waitFor();
  assert.equal(await tab('我的插件').getAttribute('aria-pressed'), 'true', 'direct link opens plugin tab');
  await tab('发现资源').click(); await page.getByRole('button', {name: question.name, exact: true}).waitFor();
  assert.doesNotMatch(await page.locator('.community-page').innerText(), /JSON|SHA-256|SDK|Raw URL|随机种子|point_codes/); await capture('community-discovery-desktop');
  await page.getByLabel('搜索社区资源', {exact: true}).fill('不存在的资源'); await page.getByRole('heading', {name: '试试更宽一些的条件'}).waitFor(); await page.getByRole('button', {name: '清空筛选', exact: true}).click();
  await page.getByLabel('资源类型', {exact: true}).selectOption('question-pack'); await page.getByLabel('适用学段', {exact: true}).selectOption('middle'); await page.getByRole('button', {name: question.name, exact: true}).waitFor(); assert.equal(await page.locator('.community-resource').count(), 1);
  await page.getByRole('button', {name: `收藏${question.name}`, exact: true}).click(); await page.getByLabel('查看范围', {exact: true}).selectOption('favorites'); await page.getByRole('button', {name: `取消收藏${question.name}`, exact: true}).waitFor();
  await page.reload(); await page.getByRole('heading', {name: '我的工具插件', exact: true}).waitFor(); await tab('发现资源').click(); await page.getByRole('button', {name: `取消收藏${question.name}`, exact: true}).waitFor();
  await installResource(question.name); const detailRegion = page.getByRole('region', {name: '资源详情'}); await detailRegion.getByRole('link', {name: '打开我的知识库'}).waitFor();
  await detailRegion.locator('summary').filter({hasText: '来源与版本'}).click(); assert.equal(await detailRegion.getByRole('link', {name: '反馈问题'}).count(), 1); assert.equal(await detailRegion.getByRole('link', {name: '参与讨论'}).count(), 0, 'unsafe external metadata cannot create a link');
  const shared = await downloadWith(detailRegion.getByRole('button', {name: '下载', exact: true}), 'question.mathtutor'); assert.equal(shared.resource.metadata.id, question.id);
  const firstCard = page.locator('.community-resource').filter({has: page.getByRole('button', {name: names[0], exact: true})}); await firstCard.getByRole('button', {name: '导入', exact: true}).click(); await page.getByRole('status').filter({hasText: '插件已导入'}).waitFor(); for (const name of names.slice(1)) await installResource(name); console.log('checked discovery, persistent favorites, scoped import/export, plugin installs');
  await tab('我的插件').click();
  for (const name of names) { assert.equal(await card(name).getByText('已停用', {exact: true}).count(), 1); assert.equal(await card(name).getByRole('button', {name: '运行工具', exact: true}).isDisabled(), true); await enable(name); }
  const exam = card('智能组卷'); await exam.getByText('运行设置', {exact: true}).click(); await exam.getByRole('spinbutton', {name: '题目数量', exact: true}).fill('6'); await exam.getByRole('button', {name: '保存并运行', exact: true}).click(); await exam.getByText('已选 2 / 请求 6 道', {exact: true}).waitFor(); assert.equal(installed.get(ids[0]).config.question_count, 6); assert.equal(await exam.locator('.community-questions > li').count(), 2);
  const reference = exam.locator('.community-result details').first(); assert.equal(await reference.evaluate(node => node.open), false, 'reference answers stay folded');
  await card('错题整理').getByRole('button', {name: '运行工具', exact: true}).click(); await card('错题整理').getByText('先检查移项时常数项的符号。', {exact: true}).waitFor();
  const report = card('学习趋势'); await report.getByRole('button', {name: '运行工具', exact: true}).click(); await report.getByRole('heading', {name: '还没有足够的实际记录'}).waitFor(); assert.equal(await report.getByRole('img').count(), 0, 'empty evidence has no chart'); assert.equal(await report.locator('.community-metrics').count(), 0);
  const emptyPending = page.waitForEvent('download'); await report.getByRole('button', {name: '保存结果', exact: true}).click(); const emptyDownload = await emptyPending; await emptyDownload.saveAs(path.join(output, 'empty-report.txt')); const emptyText = await readFile(path.join(output, 'empty-report.txt'), 'utf8'); assert.match(emptyText, /没有生成成绩或示例数据/); assert.doesNotMatch(emptyText, /0%|100%/);
  reportHasData = true; await report.getByRole('button', {name: '运行工具', exact: true}).click(); await report.getByRole('img', {name: '3 组实际作答的正确率趋势'}).waitFor(); assert.equal(await report.locator('.community-chart-point').count(), 3); await report.getByText('查看图表数据', {exact: true}).click(); assert.equal(await report.getByRole('cell', {name: '75.0%', exact: true}).count(), 1);
  const reportPending = page.waitForEvent('download'); await report.getByRole('button', {name: '保存结果', exact: true}).click(); const reportDownload = await reportPending; await reportDownload.saveAs(path.join(output, 'learning-report.txt')); assert.match(await readFile(path.join(output, 'learning-report.txt'), 'utf8'), /第 3 组：3 \/ 4 正确，正确率 75.0%/);
  console.log('checked permissions, actual exam/mistakes and empty/nonempty trend with readable saved results'); await report.scrollIntoViewIfNeeded(); await capture('community-learning-trend-desktop');
  // A catalog upgrade is a new inspected snapshot; it may never reuse old consent.
  packages[0] = {...packages[0], version: '2.0.0', changelog: '新增学习记录参考权限', required_permissions: ['question_bank', 'read_learning_records']};
  await tab('发现资源').click(); await page.getByLabel('搜索社区资源', {exact: true}).fill('智能组卷'); await page.getByRole('button', {name: '智能组卷', exact: true}).waitFor(); await page.waitForFunction(() => document.querySelector('.community-resource-meta')?.textContent.includes('2.0.0'));
  await installResource('智能组卷'); await tab('我的插件').click(); assert.equal(installed.get(ids[0]).enabled, false); assert.equal(installed.get(ids[0]).config.question_count, 6, 'upgrade retains settings'); assert.equal(await card('智能组卷').getByText('读取我的作答与核验记录', {exact: true}).count(), 1); assert.equal(await card('智能组卷').getByRole('button', {name: '运行工具', exact: true}).isDisabled(), true);
  await enable('智能组卷'); await card('智能组卷').getByRole('button', {name: '停用', exact: true}).click(); await card('智能组卷').getByText('已停用', {exact: true}).waitFor();
  const pluginExport = await downloadWith(card('错题整理').getByRole('button', {name: '下载插件', exact: true}), 'plugin.mtplugin'); assert.equal(pluginExport.id, ids[1]);
  page.once('dialog', dialog => dialog.accept()); await card('错题整理').getByRole('button', {name: '卸载', exact: true}).click(); await page.waitForFunction(() => [...document.querySelectorAll('.community-plugin h3')].every(node => node.textContent !== '错题整理'));
  console.log('checked upgrade re-consent, config preservation, export/uninstall'); const downloadedChooser = page.waitForEvent('filechooser'); await page.getByRole('button', {name: '导入下载的插件/资源', exact: true}).click(); await (await downloadedChooser).setFiles({name: '错题整理.mtplugin', mimeType: 'application/octet-stream', buffer: await readFile(path.join(output, 'plugin.mtplugin'))}); await card('错题整理').getByText('已停用', {exact: true}).waitFor(); assert.ok(installed.has(ids[1]), 'a downloaded plugin is installed directly in one file selection'); assert.equal(calls.filter(call => call.path.endsWith('/sources/import')).length, 0);
  await uploadFile(shared); await page.getByRole('status').filter({hasText: '题库已导入你的知识库'}).waitFor(); await page.getByRole('link', {name: '查看导入的题库', exact: true}).waitFor();
  await tab('社区来源').click(); await page.getByRole('textbox', {name: '来源名称', exact: true}).fill('自定义开源目录'); await page.getByRole('textbox', {name: '社区地址', exact: true}).fill('https://raw.githubusercontent.com/example/math/main/catalog.json'); await page.getByRole('button', {name: '添加来源', exact: true}).click(); await page.getByRole('heading', {name: '自定义开源目录', exact: true}).waitFor(); assert.equal(refreshCount, 0, 'adding a URL must not fetch it');
  await page.getByRole('button', {name: '刷新来源', exact: true}).click(); await page.getByText('刷新失败', {exact: true}).waitFor(); assert.equal(refreshCount, 1); assert.equal(await page.getByRole('status').filter({hasText: '来源已刷新'}).count(), 0, 'HTTP200 stale source is still a failure');
  const remote = page.locator('.community-source').filter({has: page.getByRole('heading', {name: '自定义开源目录', exact: true})}); await remote.getByRole('button', {name: '移除来源', exact: true}).click(); await page.getByRole('status').filter({hasText: '来源已移除'}).waitFor(); assert.ok(installed.has(ids[0]), 'removing a source retains installed copies');
  console.log('checked raw package import and source stale/error semantics'); await tab('创作与分享').click(); await page.getByLabel('选择要分享的知识库', {exact: true}).selectOption(library.space_id);  await page.getByRole('textbox', {name: '作者', exact: true}).fill('创作者');  await page.getByRole('textbox', {name: '一句话介绍', exact: true}).fill('一组自己整理的方程笔记。'); await page.getByRole('textbox', {name: '适用年级', exact: true}).fill('7,8'); await page.getByText('协作与反馈（可选）', {exact: true}).click(); await page.getByRole('textbox', {name: '项目主页', exact: true}).fill('https://github.com/creator/math');
  const published = await downloadWith(page.getByRole('button', {name: '打包并下载', exact: true}), 'creator-share.json'); assert.equal(published.resource.documents[0].body, '保存的实际正文夹具'); assert.equal(published.resource.project_url, 'https://github.com/creator/math');
  // Plugin creator is verified below once its validated builder has rendered.
  await page.getByRole('group', {name: '选择分享类型'}).getByRole('button', {name: '教学插件', exact: true}).click();
  await page.getByRole('region', {name: '创建教学插件'}).waitFor();
  const creator = page.getByRole('region', {name: '创建教学插件'});
  await creator.getByRole('combobox', {name: /^你想做什么/}).selectOption('mistake-review');
  page.once('dialog', dialog => dialog.accept()); await creator.getByRole('combobox', {name: /^你想做什么/}).selectOption('learning-report');
  page.once('dialog', dialog => dialog.accept()); await creator.getByRole('combobox', {name: /^你想做什么/}).selectOption('exam-builder');
  await creator.getByRole('textbox', {name: '插件名称', exact: true}).fill('每周薄弱知识点练习'); await creator.getByRole('textbox', {name: '作者署名', exact: true}).fill('创作者'); await creator.getByRole('textbox', {name: '它能帮大家做什么', exact: true}).fill('根据实际作答记录，安排下一次练习。');
  const count = creator.getByRole('spinbutton', {name: '每套题目数量', exact: true}); await count.fill('0'); const validationsBefore = mutations.filter(item => item.kind === 'validate').length; await creator.getByRole('button', {name: '保存插件', exact: true}).click(); assert.equal(await count.evaluate(node => node.validity.rangeUnderflow), true); assert.equal(mutations.filter(item => item.kind === 'validate').length, validationsBefore, 'invalid natural form stays editable without a backend request');
  await count.fill('6'); await creator.getByRole('checkbox', {name: '优先练习常出错的知识点（需要读取作答记录）', exact: true}).check();
  assert.doesNotMatch(await creator.innerText(), /JSON|SHA-256|SDK|seed|point_codes|focus_weak_skills/);
  const countBeforeCreator = installed.size, createdPlugin = await downloadWith(creator.getByRole('button', {name: '保存插件', exact: true}), 'creator-plugin.mathtutor'); assert.equal(createdPlugin.format, 'mathtutor.community-resource.v1'); assert.match(createdPlugin.resource.metadata.id, /^custom\./); assert.equal(createdPlugin.resource.package.data.schema_version, 'mathtutor.community-plugin.v1'); assert.equal(createdPlugin.resource.package.data.workflow, 'exam-builder'); assert.equal(createdPlugin.resource.package.data.defaults.question_count, 6); assert.equal(createdPlugin.resource.package.data.defaults.focus_weak_skills, true); assert.deepEqual(createdPlugin.resource.package.data.required_permissions, ['question_bank', 'read_learning_records']); assert.equal(installed.size, countBeforeCreator, 'saving a plugin does not install it');
  await creator.getByRole('combobox', {name: /^你想做什么/}).selectOption('mistake-review'); await creator.getByRole('textbox', {name: '插件名称', exact: true}).fill('每周错题复盘'); const secondCreated = await downloadWith(creator.getByRole('button', {name: '保存插件', exact: true}), 'creator-mistakes.mathtutor'); assert.equal(secondCreated.resource.package.data.workflow, 'mistake-review'); assert.notEqual(secondCreated.resource.metadata.id, createdPlugin.resource.metadata.id, 'a different workflow receives a different plugin identity'); assert.equal(installed.size, countBeforeCreator);
  console.log('checked library publish and plugin builder download without installation'); await page.setViewportSize({width: 375, height: 812}); await creator.getByRole('combobox', {name: /^你想做什么/}).scrollIntoViewIfNeeded(); await capture('community-creator-mobile');
  await tab('我的插件').click(); await card('学习趋势').getByRole('button', {name: '运行工具', exact: true}).click(); await card('学习趋势').getByRole('img').waitFor(); await card('学习趋势').scrollIntoViewIfNeeded(); await capture('community-plugin-mobile');
  await page.emulateMedia({colorScheme: 'dark', reducedMotion: 'reduce'}); await page.evaluate(() => document.documentElement.classList.add('dark')); await capture('community-plugin-mobile-dark');
  // A status refresh failure removes visible stale enabled cards, so they cannot run.
  pluginFailure = true; await page.reload(); await page.getByRole('heading', {name: '我的工具插件', exact: true}).waitFor().catch(() => {}); await tab('我的插件').click(); await page.getByRole('alert').filter({hasText: '插件服务暂时不可用'}).waitFor(); assert.equal(await page.locator('.community-plugin').count(), 0);
  pluginFailure = false; await page.getByRole('button', {name: '重读插件状态', exact: true}).click(); await card('学习趋势').waitFor();
  await page.setViewportSize({width: 667, height: 375}); const communityLink = page.getByRole('navigation', {name: '主要功能'}).getByRole('link', {name: '社区', exact: true}); await communityLink.scrollIntoViewIfNeeded(); assert.equal(await communityLink.isVisible(), true); await capture('community-landscape-sidebar');
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, 'result.json'), JSON.stringify({status: 'PASS', mocked_traffic: true, paid_model_calls: 0, mutations, screenshots, page_errors: errors, api_calls: calls.length}, null, 2));
  console.log(JSON.stringify({status: 'PASS', output, paid_model_calls: 0}));
} catch (error) { await page.screenshot({path: path.join(output, 'failure.png')}); console.error(JSON.stringify({status: 'FAIL', output, page_errors: errors, error: String(error)})); throw error; }
finally { await browser.close(); }

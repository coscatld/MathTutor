import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { type PluginRecord, type RunResult, type TrendData } from "../features/math-tutor/community/api";
import { resultText } from "../features/math-tutor/community/result-export";
import PluginWorkbench, { LearningResult, ResultView } from "../features/math-tutor/community/PluginWorkbench";

const plugin: PluginRecord = {kind: "teaching-plugin", command: "report", runtime_available: true, plugin: {schema_version: "mathtutor.community-plugin.v1", kind: "teaching-plugin", id: "example.report", name: "学习趋势", version: "1.0.0", author: "测试作者", license: "MIT", description: "实际作答记录的统计", tags: [], grades: [10], readme: "", changelog: "", workflow: "learning-report", defaults: {}, teaching_guidance: "", required_permissions: ["read_learning_records"]}, config: {window_size: 10, max_events: 500}, enabled: false, consented_permissions: [], package_hash: "a".repeat(64), installed_at: "2026-10-16", updated_at: "2026-10-16"};
test("an empty plugin list invites file import without built-in examples or recommendations", () => {
  const html = renderToStaticMarkup(<PluginWorkbench records={[]} busy={false} action={async work => work()} update={() => undefined} reload={async () => undefined} />);
  assert.match(html, /还没有导入插件/);
  assert.match(html, /选择你下载的插件文件/);
  assert.doesNotMatch(html, /发现|推荐|收藏|订阅|来源|示例|SDK/);
});

test("imported plugin stays inactive until the user agrees to the readable permissions", () => {
  const html = renderToStaticMarkup(<PluginWorkbench records={[plugin]} busy={false} action={async work => work()} update={() => undefined} reload={async () => undefined} />);
  assert.match(html, /已停用/);
  assert.match(html, /读取我的作答与核验记录/);
  assert.doesNotMatch(html, /type="checkbox"[^>]*checked/);
  assert.match(html, /同意并启用/);
  assert.doesNotMatch(html, /JSON|SHA-256|随机种子|SDK|逐项/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>[\s\S]*?运行工具/);
});

test("empty learning results do not turn absent evidence into a zero score or invented chart", () => {
  const result: RunResult = {schema_version: "mathtutor.community-result.v1", plugin_id: "example.report", plugin_version: "1.0.0", workflow: "learning-report", status: "empty", read_only: true, authority: "reference_only", config: {}, teaching_guidance: "", data: {summary: {independent_accuracy: null}, trend: []}, limitations: []};
  const html = renderToStaticMarkup(<ResultView result={result} />);
  assert.match(html, /还没有足够的实际记录/);
  assert.doesNotMatch(html, /role="img"|<polyline|0%|100%/);
  assert.match(resultText(result), /没有生成成绩或示例数据/);
  assert.doesNotMatch(resultText(result), /0%|100%|JSON|reference_only/);
});

test("learning chart uses precisely the returned groups and offers the same data as a table", () => {
  const data: TrendData = {summary: {assessed_attempts: 12, independent_attempts: 12, independent_correct: 6, independent_accuracy: .5, assisted_attempts: 0, post_solution_attempts: 0, self_report_count: 0}, trend: [.25, .5, .75].map((accuracy, index) => ({index: index + 1, attempts: 4, correct: accuracy * 4, accuracy, first_at: "2026-10-16", last_at: "2026-10-16"})), skills: [], window: {max_events: 500, included_events: 12, truncated: false}};
  const html = renderToStaticMarkup(<LearningResult data={data} />);
  assert.equal((html.match(/<circle /g) || []).length, 3);
  assert.match(html, /3 组实际作答的正确率趋势/);
  assert.match(html, /25\.0%/); assert.match(html, /50\.0%/); assert.match(html, /75\.0%/);
  assert.match(html, /查看图表数据/);
});

test("dense learning results keep every observation while limiting visual axis labels", () => {
  const data: TrendData = {summary: {assessed_attempts: 200, independent_attempts: 200, independent_correct: 100, independent_accuracy: .5, assisted_attempts: 0, post_solution_attempts: 0, self_report_count: 0}, trend: Array.from({length: 200}, (_, index) => ({index: index + 1, attempts: 1, correct: index % 2, accuracy: index % 2, first_at: "2026-10-16", last_at: "2026-10-16"})), skills: [], window: {max_events: 500, included_events: 200, truncated: false}};
  const html = renderToStaticMarkup(<LearningResult data={data} />);
  assert.equal((html.match(/<circle /g) || []).length, 200);
  assert.equal((html.match(/text-anchor="middle"/g) || []).length, 8);
  assert.equal((html.match(/<tr>/g) || []).length, 201);
});

test("empty exam result guides the user toward available questions rather than learning history", () => {
  const result: RunResult = {schema_version: "mathtutor.community-result.v1", plugin_id: "example.exam", plugin_version: "1.0.0", workflow: "exam-builder", status: "empty", read_only: true, authority: "reference_only", config: {}, teaching_guidance: "", data: {}, limitations: []};
  const html = renderToStaticMarkup(<ResultView result={result} />);
  assert.match(html, /没有符合条件的题目/);
  assert.doesNotMatch(html, /还没有足够的实际记录|当前没有生成示例成绩/);
});

test("exam answers stay absent when the actual result says answers were not included", () => {
  const result: RunResult = {schema_version: "mathtutor.community-result.v1", plugin_id: "example.exam", plugin_version: "1.0.0", workflow: "exam-builder", status: "ok", read_only: true, authority: "reference_only", config: {}, teaching_guidance: "", limitations: [], data: {title: "练习", requested_count: 1, actual_count: 1, seed: 42, answers_included: false, questions: [{id: "q", text: "解方程2x=4", point_title: "一元一次方程", grade: 7, reference_answer: "private-reference-answer"}]}};
  const html = renderToStaticMarkup(<ResultView result={result} />);
  assert.match(html, /解方程/);
  assert.doesNotMatch(html, /private-reference-answer|参考答案与说明|随机种子|seed|JSON/);
  assert.doesNotMatch(resultText(result), /private-reference-answer|参考答案/);
});


test("code plugins require explicit local trust and do not expose learning-report settings", () => {
  const code = {...plugin, kind: "code-plugin" as const, command: "explain", runtime_available: true, plugin: {...plugin.plugin, schema_version: "mathtutor.code-plugin.v1" as const, kind: "code-plugin" as const, workflow: "code" as const, runtime: "python" as const, entrypoint: "main.py", file_hashes: {"main.py": "a".repeat(64)}, required_permissions: ["execute_local_code" as const]}};
  const html = renderToStaticMarkup(<PluginWorkbench records={[code]} busy={false} action={async work => work()} update={() => undefined} reload={async () => undefined} />);
  assert.match(html, /以你的账户权限运行/); assert.match(html, /不是隔离沙盒/);
  assert.match(html, /我信任此插件，允许在本机运行代码/);
  assert.match(html, /type="checkbox"/); assert.doesNotMatch(html, /type="checkbox"[^>]*checked/);
  assert.match(html, /disabled=""[^>]*>[\s\S]*?同意并启用/);
  assert.match(html, /本次运行请求/); assert.match(html, /\/explain/);
  assert.doesNotMatch(html, /每组作答数|参考最近多少条|不会修改你的成绩或学习记录/);
  const unavailable = renderToStaticMarkup(<PluginWorkbench records={[{...code, enabled: true, runtime_available: false}]} busy={false} action={async work => work()} update={() => undefined} reload={async () => undefined} />);
  assert.match(unavailable, /暂时没有此插件所需的运行环境/);
  assert.match(unavailable, /disabled=""[^>]*>[\s\S]*?运行插件/);
});

test("code results use real returned text and values without claiming read-only or verified learning", () => {
  const result: RunResult = {schema_version: "mathtutor.community-result.v1", plugin_id: "fixture.code", plugin_version: "1.0.0", workflow: "code", status: "ok", read_only: false, sandboxed: false, execution_mode: "trusted_local_code", authority: "reference_only", config: {}, teaching_guidance: "", data: {text: "实际返回的三角函数说明", count: 3}, limitations: []};
  const html = renderToStaticMarkup(<ResultView result={result} />);
  assert.match(html, /实际返回的三角函数说明/); assert.match(html, /count/);
  assert.doesNotMatch(html, /只读分析|独立正确率|已掌握/);
  assert.match(resultText(result), /实际返回的三角函数说明/); assert.match(resultText(result), /count/);
});

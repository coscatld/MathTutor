import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { gradeLabel, publicHttps, resourceAdded, type PluginRecord, type Resource, type RunResult, type TrendData } from "../features/math-tutor/community/api";
import { resultText } from "../features/math-tutor/community/result-export";
import PluginWorkbench, { LearningResult, ResultView } from "../features/math-tutor/community/PluginWorkbench";

const plugin: PluginRecord = {plugin: {schema_version: "mathtutor.community-plugin.v1", kind: "teaching-plugin", id: "example.report", name: "学习趋势", version: "1.0.0", author: "测试作者", license: "MIT", description: "实际作答记录的统计", tags: [], grades: [10], readme: "", changelog: "", workflow: "learning-report", defaults: {}, teaching_guidance: "", required_permissions: ["read_learning_records"]}, config: {window_size: 10, max_events: 500}, enabled: false, consented_permissions: [], package_hash: "a".repeat(64), installed_at: "2026-10-16", updated_at: "2026-10-16"};
const resource: Resource = {id: "example.report", plugin_id: "example.report", name: "学习趋势", version: "1.0.0", type: "plugin", author: "测试作者", license: "MIT", description: "统计", tags: [], grades: [10], readme: "", changelog: "", package_sha256: "a".repeat(64), package_size_bytes: 800, project_example: true, source_id: "builtin", source_name: "项目示例", favorite: false, imported_versions: [], latest_imported_version: null, update_status: "not_imported", importable: true, permissions: ["read_learning_records"]};

test("community external links accept HTTPS metadata and reject credentials or executable schemes", () => {
  assert.equal(publicHttps("https://github.com/example/project/issues"), "https://github.com/example/project/issues");
  for (const value of ["javascript:alert(1)", "data:text/html,<script>", "http://example.com", "https://user:secret@example.com", "//example.com", null]) assert.equal(publicHttps(value), null);
});

test("added resources reflect imported history or actual installed plugin identity", () => {
  assert.equal(resourceAdded(resource), false);
  assert.equal(resourceAdded(resource, [plugin]), true);
  assert.equal(resourceAdded({...resource, type: "question-pack"}, [plugin]), false);
  assert.equal(resourceAdded({...resource, type: "question-pack", imported_versions: ["1.0.0"]}), true);
  assert.equal(resourceAdded({...resource, imported_versions: ["1.0.0"], installed_version: null}), false, "uninstalling a plugin retains history without claiming it is installed");
  assert.equal(gradeLabel([1, 7, 12]), "小学 / 初中 / 高中");
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

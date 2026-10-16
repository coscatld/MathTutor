import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  PointDetail,
  GradeFilter,
  QuestionBankTree,
  StageFirstRun,
  StageSwitcher,
} from "../features/math-tutor/desktop/components/QuestionBankPanel";
import { LearnerStageForm } from "../features/math-tutor/desktop/components/LearnerStagePanel";
import {
  buildDemoLaunch,
  buildPracticeLaunch,
  buildReferenceLaunch,
  difficultyStars,
  filterBankTerms,
  parseTutorLaunch,
  tutorLaunchHref,
} from "../features/math-tutor/desktop/lib/question-bank";
import type { BankPointDetail, BankReferenceProblem, QuestionBank } from "../features/math-tutor/lib/question-bank-types";

const noop = () => {};

const BANK: QuestionBank = {
  version: "k12-pep-v1",
  stage: "middle",
  source_note: "参照人教版教材目录整理，学校进度可能不同",
  terms: [
    { code: "g7b", stage: "middle", grade: 7, order: 14, label: "七年级下册", book: "人教版 数学 七年级下册", units: [
      { code: "g7b-u8", title: "第八章 二元一次方程组", points: [{ code: "g7b-u8-p1", title: "代入消元法", problem_count: 4, demo_count: 0 }] },
    ] },
    { code: "g7a", stage: "middle", grade: 7, order: 13, label: "七年级上册", book: "人教版 数学 七年级上册", units: [
      { code: "g7a-u3", title: "第三章 一元一次方程", points: [
        { code: "g7a-u3-p2", title: "解一元一次方程——移项", problem_count: 6, demo_count: 1 },
        { code: "g7a-u3-p9", title: "实际问题与一元一次方程", problem_count: 0, demo_count: 0 },
      ] },
    ] },
  ],
};

const DETAIL: BankPointDetail = {
  point: { code: "g7a-u3-p2", title: "解一元一次方程——移项", term: "七年级上册", unit: "第三章 一元一次方程" },
  problems: [
    { id: "g7a-u3-p2-1", text: "3x-5=10", display_latex: "3x - 5 = 10", family: "linear", difficulty: 1 },
    { id: "g7a-u3-p2-2", text: "5x+2=3x-6", display_latex: "5x + 2 = 3x - 6", family: "linear", difficulty: 3 },
  ],
  demos: [{ title: "看等式两边的平衡", request: "画出 y=2x+3 和 y=7" }],
  note: "",
};

test("QuestionBankTree: terms in order, point badges and the empty note", () => {
  const html = renderToStaticMarkup(<QuestionBankTree bank={BANK} onSelect={noop} />);
  assert.ok(html.indexOf("七年级上册") < html.indexOf("七年级下册"), "terms sorted by order");
  assert.ok(html.includes("6 题"));
  assert.ok(html.includes("4 题"));
  assert.ok(html.includes("演示"));
  assert.ok(html.includes("暂无可核验题目"));
  assert.ok(html.includes("查看知识点：解一元一次方程——移项"));
  assert.ok(html.includes("<ol") && html.includes("<ul"), "semantic lists");
});

test("QuestionBankTree: search filters point titles", () => {
  const html = renderToStaticMarkup(<QuestionBankTree bank={BANK} query="代入" onSelect={noop} />);
  assert.ok(html.includes("代入消元法"));
  assert.ok(!html.includes("移项"));
  assert.deepEqual(filterBankTerms(BANK.terms, "").map(t => t.code), ["g7a", "g7b"]);
  assert.equal(filterBankTerms(BANK.terms, "不存在").length, 0);
});

test("StageSwitcher: offers 小学/初中/高中 and marks the viewed stage", () => {
  const html = renderToStaticMarkup(<StageSwitcher value="middle" onChange={noop} />);
  assert.ok(html.includes("临时查看其他学段"));
  for (const label of ["小学", "初中", "高中"]) assert.ok(html.includes(label));
  assert.match(html, /aria-pressed="true"[^>]*>初中</);
});

test("PointDetail: problems with stars and start buttons, demos with 看演示", () => {
  const html = renderToStaticMarkup(<PointDetail detail={DETAIL} onLaunch={noop} />);
  assert.ok(html.includes("★"));
  assert.ok(html.includes("★★★"));
  assert.equal((html.match(/开始练习：/g) || []).length, 2);
  assert.ok(html.includes("看演示：看等式两边的平衡"));
  assert.ok(html.includes("katex"), "LaTeX rendered with math");
  assert.equal(difficultyStars(2), "★★");
  assert.equal(difficultyStars(0), "★");
});

test("PointDetail: shows the note when nothing is verifiable", () => {
  const note = "这个知识点暂无可核验题目，可以把题目发给 Tutor 讲解";
  const html = renderToStaticMarkup(<PointDetail detail={{ ...DETAIL, problems: [], demos: [], note }} onLaunch={noop} />);
  assert.ok(html.includes(note));
  assert.ok(!html.includes("开始练习"));
});

test("StageFirstRun: asks for a stage before showing the tree", () => {
  const html = renderToStaticMarkup(<StageFirstRun onPick={noop} />);
  assert.ok(html.includes("先选择你的学段"));
  for (const label of ["选择学段：小学", "选择学段：初中", "选择学段：高中"]) assert.ok(html.includes(label));
});

test("LearnerStageForm: grade options only for the chosen stage", () => {
  const high = renderToStaticMarkup(<LearnerStageForm stage="high" grade={null} onStage={noop} onGrade={noop} onSave={noop} />);
  const grades = [...high.matchAll(/<option value="(\d+)"/g)].map(match => Number(match[1]));
  assert.deepEqual(grades, [10, 11, 12]);
  assert.ok(high.includes("高一") && high.includes("高三"));
  assert.ok(!high.includes(">七年级<") && !high.includes(">一年级<"));
  assert.ok(high.includes("不设置"));
  const none = renderToStaticMarkup(<LearnerStageForm stage={null} grade={null} onStage={noop} onGrade={noop} onSave={noop} />);
  assert.ok(!none.includes("<select"));
});

test("launch helpers: start practice → submit_problem, demo → send_message", () => {
  assert.deepEqual(buildPracticeLaunch(DETAIL.problems[0]), { command: "submit_problem", payload: { text: "3x-5=10" } });
  assert.deepEqual(buildDemoLaunch(DETAIL.demos[0]), { command: "send_message", payload: { text: "画出 y=2x+3 和 y=7" } });
  const href = tutorLaunchHref(buildPracticeLaunch(DETAIL.problems[0]), "s-1");
  assert.ok(href.startsWith("/math-tutor?"));
  const params = new URLSearchParams(href.split("?")[1]);
  assert.equal(params.get("session"), "s-1");
  assert.deepEqual(parseTutorLaunch(params), { command: "submit_problem", payload: { text: "3x-5=10" } });
  const demo = new URLSearchParams(tutorLaunchHref(buildDemoLaunch(DETAIL.demos[0]), "s-2").split("?")[1]);
  assert.deepEqual(parseTutorLaunch(demo), { command: "send_message", payload: { text: "画出 y=2x+3 和 y=7" } });
});

test("parseTutorLaunch: rejects empty and over-long text", () => {
  assert.equal(parseTutorLaunch(new URLSearchParams("session=a")), null);
  assert.equal(parseTutorLaunch(new URLSearchParams("start=%20%20")), null);
  assert.equal(parseTutorLaunch(new URLSearchParams({ ask: "x".repeat(301) })), null);
  assert.equal(parseTutorLaunch(new URLSearchParams({ ask: "x".repeat(300) }))?.payload.text.length, 300);
  assert.equal(parseTutorLaunch(null), null);
});

const REFERENCE: BankReferenceProblem = { id: "reference-1", text: "证明等腰三角形的两个底角相等。", reference_answer: "两个底角相等", explanation: "作顶角平分线，利用全等三角形证明。", difficulty: 2, category: "推理与证明", verification: { mode: "reference", answer_check: null, student_steps_auto_verified: false } };

test("reference-only points are available and counted separately from step verification", () => {
  const bank: QuestionBank = { ...BANK, terms: [{ ...BANK.terms[0], units: [{ code: "u", title: "证明", points: [{ code: "p", title: "等腰三角形", problem_count: 0, reference_count: 2, total_count: 2, demo_count: 0 }] }] }] };
  const html = renderToStaticMarkup(<QuestionBankTree bank={bank} onSelect={noop} />);
  assert.ok(html.includes("2 题 · 参考"));
  assert.ok(!html.includes("暂无可核验题目"));
  assert.ok(!html.includes("题 · 可核验"));
});

test("reference answers are closed by default with an explicit grading boundary", () => {
  const html = renderToStaticMarkup(<PointDetail detail={{ ...DETAIL, problems: [], demos: [], reference_problems: [REFERENCE] }} onLaunch={noop} />);
  const details = html.match(/<details\b[^>]*>/g) || [];
  assert.equal(details.length, 1);
  assert.ok(details.every(tag => !/\sopen(?:\s|=|>)/.test(tag)));
  assert.ok(html.includes("查看参考答案与解析"));
  assert.ok(html.includes("参考答案，作答过程未自动核验"));
  assert.ok(html.includes("请 Tutor 讲解"));
  assert.ok(!html.includes("开始练习"));
  assert.ok(html.includes(REFERENCE.explanation));
});

test("reference launch only sends the complete question through ordinary chat", () => {
  const launch = buildReferenceLaunch(REFERENCE)!;
  assert.deepEqual(launch, { command: "send_message", payload: { text: REFERENCE.text } });
  assert.deepEqual(Object.keys(launch.payload), ["text"]);
  const params = new URLSearchParams(tutorLaunchHref(launch, "reference-session").split("?")[1]);
  assert.equal(params.get("ask"), REFERENCE.text);
  assert.equal(params.get("start"), null);
  assert.deepEqual(parseTutorLaunch(params), launch);
  assert.deepEqual([...params.keys()], ["session", "ask"]);
  assert.equal(buildReferenceLaunch({ text: "x".repeat(301) }), null);
  assert.equal(buildReferenceLaunch({ text: " " }), null);
  assert.equal(buildReferenceLaunch({ text: "x".repeat(300) })?.payload.text.length, 300);
});

test("grade filtering respects cross-grade recommended courses and legacy grade metadata", () => {
  const terms = [{ ...BANK.terms[0], code: "h2a", grade: 11, recommended_grades: [11] }, { ...BANK.terms[1], code: "h3a", grade: 12, recommended_grades: [11, 12] }];
  assert.deepEqual(filterBankTerms(terms, "", 11).map(t => t.code).sort(), ["h2a", "h3a"]);
  assert.deepEqual(filterBankTerms(terms, "", 12).map(t => t.code), ["h3a"]);
  assert.equal(filterBankTerms(BANK.terms, "", 7).length, 2);
  assert.equal(filterBankTerms(terms, "移项", 11).length, 1);
  const html = renderToStaticMarkup(<GradeFilter stage="high" value={11} onChange={noop} />);
  for (const label of ["全部年级", "高一", "高二", "高三"]) assert.ok(html.includes(label));
  assert.match(html, /<option value="11" selected="">高二<\/option>/);
});

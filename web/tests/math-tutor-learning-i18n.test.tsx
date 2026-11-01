import test from "node:test";
import assert from "node:assert/strict";
import React, {type ReactNode} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {I18nProvider} from "../lib/i18n";
import {LearningOverview, SkillObservation} from "../features/math-tutor/desktop/components/LearningProfilePanel";
import PracticeOfferCard from "../features/math-tutor/desktop/components/PracticeOfferCard";
import {BootstrapStatusControl} from "../features/math-tutor/desktop/components/BootstrapStatus";
import ReadinessBadge from "../features/math-tutor/desktop/components/ReadinessBadge";
import {GradeFilter, PointDetail, StageFirstRun} from "../features/math-tutor/desktop/components/QuestionBankPanel";

const english = (children: ReactNode) => renderToStaticMarkup(<I18nProvider initialLocale="en">{children}</I18nProvider>);
const noop = () => {};

test("English learning profile translates fixed observations and counts", () => {
  const html = english(<SkillObservation skill={{code:"fraction_operations", label:"分数运算", mastery:null, grade_band:null,
    observation:"有 3 道新题首次独立完成，仍可换题检查。", evidence_count:4, joint_task_evidence:2,
    counts:{independent:{correct:3,incorrect:1}}}} onEvidence={noop} />);
  assert.ok(html.includes("Fraction operations"));
  assert.ok(html.includes("3 new problem(s) completed independently on the first attempt"));
  assert.ok(html.includes("Correct 3 · Incorrect 1"));
  assert.ok(html.includes("2 multi-skill records"));
  assert.ok(!/[\u3400-\u9fff]/u.test(html));
  const overview = english(<LearningOverview summary={{skills:[],total_attempts:0,active_misconceptions:0,has_independent_evidence:false}} />);
  assert.ok(overview.includes("Start with an independent response") && overview.includes("not a mastery percentage"));
});

test("English recommendation keeps response modes and diagnostic counts distinct", () => {
  const html = english(<PracticeOfferCard offer={{offer_id:"offer",status:"ACCEPTED",display_status:"completed",parent_cycle_id:"parent",
    title:"选择题诊断练习",skill_labels:["分数运算"],concept_labels:[],difficulty:"2",offered_at:"2026-10-28",expires_at:"2026-10-29",
    response_mode:"single_choice",observation_kind:"diagnostic",reason:"用选择题观察当前知识点的作答情况；这类记录用于诊断，不作为首次独立自由作答。",
    evidence_href:"/math-tutor/profile?cycle=original",result_summary:{observations:3,diagnostic_correct:2,first_free_response:1,independent_correct:1,helped:0}}}
    accepting={false} onStart={noop} />);
  assert.ok(html.includes("Multiple-choice diagnostic practice"));
  assert.ok(html.includes("Problem difficulty 2/5 (not a student level)"));
  assert.ok(html.includes("2 correct diagnostic choices; 1 first independent free responses"));
  assert.ok(html.includes('href="/math-tutor/profile?cycle=original"'));
  assert.ok(!/[\u3400-\u9fff]/u.test(html));
});

test("English question-bank controls preserve original questions and reference content", () => {
  const stage = english(<StageFirstRun onPick={noop} />);
  assert.ok(stage.includes("Choose your school stage") && stage.includes("Primary school"));
  assert.ok(stage.includes('aria-label="Choose school stage: Middle school"'));
  const grades = english(<GradeFilter stage="middle" value={7} onChange={noop} />);
  assert.ok(grades.includes("All grades") && grades.includes("Grade 7"));
  const html = english(<PointDetail detail={{point:{code:"p",title:"课程知识点原文",term:"七年级上册",unit:"课程单元原文"},problems:[],demos:[],note:"",
    reference_problems:[{id:"ref",text:"请解原题：x + 1 = 3",category:"基础与应用",difficulty:2,verification:{mode:"reference",answer_check:null,student_steps_auto_verified:false},reference_answer:"参考正文原文 x=2",explanation:"讲解正文原文"}]}} onLaunch={noop} />);
  assert.ok(html.includes("View reference answer and explanation"));
  assert.ok(html.includes("Reference answer; your working is not automatically verified"));
  assert.ok(html.includes("请解原题：x + 1 = 3") && html.includes("参考正文原文 x=2") && html.includes("讲解正文原文"));
  assert.ok(html.includes('aria-label="Ask Tutor to explain: 请解原题：x + 1 = 3"'));
});

test("English startup status translates known backend labels without exposing internal codes", () => {
  const html = english(<BootstrapStatusControl payload={{phase:"READY",readiness:"DEGRADED",reason:"未配置模型提供商（可继续使用模板辅导与词汇检索）",
    steps:[{key:"secret_store",label:"凭据库",status:"ok",detail:"开发/测试内存凭据库"}]}} open refreshing={false} onToggle={noop} onRefresh={noop} />);
  assert.ok(html.includes('aria-label="System status: Some features available"'));
  assert.ok(html.includes("Credential store") && html.includes("In-memory credential store for development/testing"));
  assert.ok(html.includes("No model provider is configured"));
  assert.ok(!/[\u3400-\u9fff]/u.test(html));
  const badge = english(<ReadinessBadge readiness={{status:"READY",checks:{},reasons:{}}} />);
  assert.ok(badge.includes('aria-label="System status: Ready"'));
});

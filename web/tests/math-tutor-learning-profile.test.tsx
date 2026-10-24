import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {ItemErrorObservations, LearningOverview, SkillObservation} from "../features/math-tutor/desktop/components/LearningProfilePanel";
import ReferenceJourney from "../features/math-tutor/knowledge/ReferenceJourney";
import StageReviewPanel from "../features/math-tutor/knowledge/StageReviewPanel";
import {referenceSelectionHref, withTutorSession} from "../features/math-tutor/lib/workspace-navigation";
import {groupOffers} from "../features/math-tutor/desktop/components/OffersPanel";
import PracticeOfferCard from "../features/math-tutor/desktop/components/PracticeOfferCard";
import DataPrivacySettings from "../features/math-tutor/desktop/components/DataPrivacySettings";
import type {PracticeOffer} from "../features/math-tutor/desktop/types";

const offer: PracticeOffer = {offer_id:"offer",status:"ACTIVE",skill_labels:["移项"],concept_labels:[],difficulty:"medium",offered_at:"2026-09-13",expires_at:"2026-09-15",parent_cycle_id:"parent"};
test("learning observation precedes collapsed evidence and preserves unknown mastery", () => {
  const html = renderToStaticMarkup(<SkillObservation skill={{code:"skill", label:"移项",mastery:null,grade_band:null,observation:"尚未检查",counts:{independent:{correct:0,incorrect:0}}}} onEvidence={() => {}}/>);
  assert.ok(html.indexOf("尚未检查") < html.indexOf("证据计数"));
  assert.ok(html.includes("<details") && !html.includes('open=""'));
  assert.ok(!html.includes("0%") && !html.includes("掌握度"));
});
test("learning overview offers an independent attempt until verified evidence exists", () => {
  const summary = {skills: [], total_attempts: 0, active_misconceptions: 0, has_conversations: true, has_independent_evidence: false};
  const empty = renderToStaticMarkup(<LearningOverview summary={summary} />);
  assert.ok(empty.includes("先留下一次独立作答") && empty.includes('href="/math-tutor"'));
  assert.ok(!empty.includes('href="/math-tutor/offers"'));
  const observed = renderToStaticMarkup(<LearningOverview summary={{...summary, has_independent_evidence:true}} />);
  assert.ok(observed.includes('href="/math-tutor/offers"') && observed.includes("不是掌握比例"));
});
test("independent, assisted and post-solution answers remain visibly separate", () => {
  const html = renderToStaticMarkup(<SkillObservation skill={{code:"skill", label:"移项",mastery:null,grade_band:null,evidence_count:6,counts:{independent:{correct:1,incorrect:1},assisted:{correct:2,incorrect:0},post_solution:{correct:2,incorrect:0}}}} onEvidence={() => {}} />);
  const visible = html.slice(0, html.indexOf("<details"));
  assert.match(visible, /独立答对<\/dt><dd>1/);
  assert.match(visible, /受助答对<\/dt><dd>2/);
  assert.match(visible, /答案后答对<\/dt><dd>2/);
  assert.ok(!visible.includes("掌握率") && !visible.includes("%"));
});
test("missing assistance counts stay unknown instead of becoming zero successes", () => {
  const html = renderToStaticMarkup(<SkillObservation skill={{code:"skill", label:"移项",mastery:null,grade_band:null,evidence_count:1}} onEvidence={() => {}} />);
  assert.match(html, /独立答对<\/dt><dd>待确认/);
  assert.match(html, /受助答对<\/dt><dd>待确认/);
});
test("unlocalized multi-skill errors remain item observations with a route to their evidence", () => {
  const summary = {skills: [], total_attempts: 1, active_misconceptions: 0, item_error_observations: [{
    rule_id:"SIGN_ERROR", label:"符号错误", event_id:"event", assessment_id:"assessment", cycle_id:"cycle",
    related_skill_ids:["equality", "isolate", "substitution"], last_seen_at:null,
    status:"unlocalized" as const, correction_event_id:null,
  }]};
  const html = renderToStaticMarkup(<ItemErrorObservations summary={summary} onEvidence={() => {}} />);
  assert.ok(html.includes("整题错误观察") && html.includes("具体技能待定位"));
  assert.ok(html.includes("不代表相关技能都存在问题"));
  assert.ok(html.includes('aria-label="查看符号错误的整题记录"'));
  assert.ok(!html.includes("equality") && !html.includes("掌握"));
  const corrected = renderToStaticMarkup(<ItemErrorObservations summary={{...summary,
    item_error_observations:[{...summary.item_error_observations[0], status:"corrected_later", correction_event_id:"correct"}],
  }} onEvidence={() => {}} />);
  assert.ok(corrected.includes("该题后来答对，技能仍待独立检验"));
  assert.equal(renderToStaticMarkup(<ItemErrorObservations summary={{...summary, item_error_observations:undefined}} onEvidence={() => {}} />), "");
});
test("reference workflow preserves the conversation and opens its existing selector", () => {
  const href = referenceSelectionHref("c/中文&scope=all");
  const target = new URL(href, "https://mathtutor.test");
  assert.equal(target.searchParams.get("session"), "c/中文&scope=all");
  assert.equal(target.searchParams.get("panel"), "documents");
  assert.equal(target.searchParams.get("scope"), null);
  const html = renderToStaticMarkup(<ReferenceJourney conversationId="current" />);
  assert.ok(html.includes("选择当前对话资料") && html.includes("session=current&amp;panel=documents"));
  assert.ok(html.includes("保存资料不会自动开放给所有对话"));
});
test("assigning a new session preserves a requested reference panel and launch text", () => {
  const reference = new URL(withTutorSession(new URLSearchParams("panel=documents"), "fresh"), "https://mathtutor.test");
  assert.equal(reference.searchParams.get("panel"), "documents");
  assert.equal(reference.searchParams.get("session"), "fresh");
  const launch = new URL(withTutorSession(new URLSearchParams({ask:"解释 x + 1 = 3", session:" "}), "fresh"), "https://mathtutor.test");
  assert.equal(launch.searchParams.get("ask"), "解释 x + 1 = 3");
  assert.equal(launch.searchParams.get("session"), "fresh");
});
test("stage review distinguishes loading from an empty learning history", () => {
  const html = renderToStaticMarkup(<StageReviewPanel />);
  assert.ok(html.includes("正在读取阶段复盘"));
  assert.ok(!html.includes("还没有阶段复盘") && !html.includes("尚无复盘"));
  assert.ok(html.includes("<details") && !html.includes('open=""'));
});
test("accepted does not mean completed and ongoing action is continue", () => {
  const active = {...offer,status:"ACCEPTED" as const,display_status:"in_progress" as const,resume_session_id:"s"};
  const groups = groupOffers([offer,active]);
  assert.equal(groups.inProgress.length,1);
  assert.equal(groups.completed.length,0);
  const html = renderToStaticMarkup(<PracticeOfferCard offer={active} accepting={false} onStart={() => {}}/>);
  assert.ok(html.includes("继续练习") && !html.includes("开始练习"));
});
test("completed practice links directly to its new evidence", () => {
  const completed = {...offer,status:"ACCEPTED" as const,display_status:"completed" as const,evidence_href:"/math-tutor/profile?cycle=c",result_summary:{independent_correct:1,helped:0,observations:1}};
  const html=renderToStaticMarkup(<PracticeOfferCard offer={completed} accepting={false} onStart={() => {}}/>);
  assert.ok(html.includes("查看学习记录") && html.includes("profile?cycle=c"));
  assert.ok(!html.includes("开始练习") && !html.includes("掌握"));
});
test("data maintenance is embedded in settings instead of a second modal", () => {
  const html=renderToStaticMarkup(<DataPrivacySettings/>);
  assert.ok(html.includes("数据与隐私"));
  assert.ok(!html.includes('role="dialog"') && !html.includes('aria-modal="true"'));
});

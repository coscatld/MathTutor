import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {SkillObservation} from "../features/math-tutor/desktop/components/LearningProfilePanel";
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

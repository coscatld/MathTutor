import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import PracticeOfferCard from "../features/math-tutor/desktop/components/PracticeOfferCard";
import { difficultyLabel, offerExpiryLabel, offerStatusLabel } from "../features/math-tutor/desktop/lib/labels";
import type { PracticeOffer } from "../features/math-tutor/desktop/types";

function makeOffer(overrides: Partial<PracticeOffer> = {}): PracticeOffer {
  return {
    offer_id: "offer-1",
    status: "ACTIVE",
    skill_labels: ["分数乘法"],
    concept_labels: ["分数"],
    difficulty: "medium",
    offered_at: "2026-08-20T09:00:00Z",
    expires_at: "2026-08-20T12:00:00Z",
    parent_cycle_id: "cycle-9",
    ...overrides,
  };
}

test("PracticeOfferCard: active offer renders public labels and an enabled start button", () => {
  const html = renderToStaticMarkup(
    <PracticeOfferCard offer={makeOffer()} accepting={false} onStart={() => undefined} />,
  );
  assert.ok(html.includes("待开始"), "shows ACTIVE label");
  assert.ok(html.includes("分数乘法"), "shows skill label");
  assert.ok(html.includes("分数"), "shows concept label");
  assert.ok(html.includes("本次观察"), "shows observation goal");
  assert.ok(html.includes("开始练习"), "shows start button");
  assert.ok(!html.includes('disabled=""'), "active offer button is enabled");
  assert.ok(!html.includes("过期"), "no expiry pressure on pending practice");
});

test("PracticeOfferCard: REVOKED offer is disabled and shows no expiry countdown", () => {
  const html = renderToStaticMarkup(
    <PracticeOfferCard offer={makeOffer({ status: "REVOKED" })} accepting={false} onStart={() => undefined} />,
  );
  assert.ok(html.includes("历史建议"), "shows REVOKED label");
  assert.ok(!html.includes("开始练习"), "no start action on inactive practice");
  assert.ok(!html.includes("任务失败"), "expiry is not a learning failure");
});

test("PracticeOfferCard: EXPIRED offer is disabled", () => {
  const html = renderToStaticMarkup(
    <PracticeOfferCard offer={makeOffer({ status: "EXPIRED", expires_at: "2026-08-19T00:00:00Z" })} accepting={false} onStart={() => undefined} />,
  );
  assert.ok(html.includes("历史建议"), "shows EXPIRED label");
  assert.ok(!html.includes("开始练习"), "no start action on inactive practice");
});

test("PracticeOfferCard: accepting state disables the button", () => {
  const html = renderToStaticMarkup(
    <PracticeOfferCard offer={makeOffer()} accepting={true} onStart={() => undefined} />,
  );
  assert.ok(html.includes("正在处理…"), "shows accepting state");
  assert.ok(html.includes('disabled=""'), "button disabled while accepting");
});

test("PracticeOfferCard: never exposes mastery/answer/solution/attestation material", () => {
  const html = renderToStaticMarkup(
    <PracticeOfferCard offer={makeOffer()} accepting={false} onStart={() => undefined} />,
  );
  for (const forbidden of ["掌握度", "答案", "解答", "认证", "attest", "mastery"]) {
    assert.ok(!html.includes(forbidden), `must not contain ${forbidden}`);
  }
});

test("offer labels: status/difficulty fall back to raw value for unknown codes", () => {
  assert.equal(offerStatusLabel("ACTIVE"), "可练习");
  assert.equal(offerStatusLabel("WEIRD"), "WEIRD");
  assert.equal(difficultyLabel("hard"), "挑战");
  assert.equal(difficultyLabel("unknown"), "unknown");
});

test("offerExpiryLabel: computes friendly expiry text", () => {
  const now = "2026-08-20T10:00:00Z";
  assert.equal(offerExpiryLabel("2026-08-20T13:00:00Z", now), "3 小时后过期");
  assert.equal(offerExpiryLabel("2026-08-20T10:02:00Z", now), "2 分钟后过期");
  assert.equal(offerExpiryLabel("2026-08-20T10:00:30Z", now), "即将过期");
  assert.equal(offerExpiryLabel("2026-08-20T09:59:00Z", now), "已过期");
  assert.equal(offerExpiryLabel("not-a-date", now), "");
});

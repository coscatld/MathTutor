import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { I18nProvider } from "../lib/i18n";
import { explorationApi, ExplorationApiError, type CheckPrompt, type EvidenceCard, type ExplorationView } from "../features/math-tutor/exploration/api";
import { ExplorationRequests } from "../features/math-tutor/exploration/requests";
import { SourceCard, SourceComparison, sourceHref } from "../features/math-tutor/exploration/SourceReading";
import LearningPanel, { IndependentCheck, LearningFeedback } from "../features/math-tutor/exploration/LearningPanel";
import { ConnectionForm } from "../features/math-tutor/exploration/ZhihuConnection";
import ExplorationWorkbench from "../features/math-tutor/exploration/ExplorationWorkbench";

const card: EvidenceCard = {
  source_id: "source-one", span_id: "span-one", title: "原文中的数学问题", author: "原作者",
  original_url: "https://www.zhihu.com/question/123/answer/456?utm_campaign=hackathon",
  quote: '原文 <img src=x onerror="window.hacked=true"> √(x²) = |x|',
  context: "前提 x 是实数。原文中的结论还需要检查条件。", reading_question: "AI 建议：原文限定了什么范围？",
};
const check: CheckPrompt = {
  check_id: "roots-next", concept_id: "roots", prompt: "当前题目：当 x = −2 时，√(x²) 等于多少？",
  response_type: "number", choices: [], purpose: "transfer",
};
const view: ExplorationView = {
  inquiry_id: "11d031d4-8fef-4375-8fe5-c0b72be3078f", revision: 3, updated_at: "2026-11-18T02:00:00Z",
  question: "为什么根号 x² 不总是 x？", goal: "understand", reflection: "还要注意定义域。", ai_status: "unavailable",
  organization_attempts: 1, last_feedback: "此前题目的解释。", last_correctness: "explanation", observation_count: 1,
  last_check: { ...check, check_id: "roots-previous", prompt: "上一题：当 x = −3 时，√(x²) 等于多少？" },
  evidence: { question: "为什么根号 x² 不总是 x？", sources: [], spans: [], cards: [card], interpretations: [], comparisons: [],
    gaps: [], rejected_candidate_items: [], source_rejections: [], unselected_source_ids: [], distinct_excerpt_count: 1, status: "evidence_available" },
  learning: { original_question: "为什么根号 x² 不总是 x？", goal: "understand", target_concept: "roots", concept_title: "平方根",
    evidence_state: "assisted_only", independent_successes: 0, basis_observation_ids: ["seen-one"],
    steps: [{ step_id: "read", concept_id: "roots", action: "read", title: "先看定义", reason: "区分平方与算术平方根", basis_observation_ids: [] }],
    check, prerequisite_basis: "authored_curriculum" },
};

test("source excerpts and AI questions remain escaped, attributed text in both languages", () => {
  for (const locale of ["zh-CN", "en"] as const) {
    const html = renderToStaticMarkup(<I18nProvider initialLocale={locale}><SourceCard card={card} index={0} selected={false} selectionFull={false}
      sourceText="完整收到的检索摘录 <script>bad()</script>" warnings={["possible_missing_formula"]} onSelect={() => {}} /></I18nProvider>);
    assert.match(html, /原作者/); assert.match(html, /原文中的数学问题/); assert.match(html, /AI 建议：原文限定了什么范围？/);
    assert.match(html, /&lt;img/); assert.match(html, /&lt;script&gt;/); assert.doesNotMatch(html, /<img|<script|<math/);
    assert.match(html, /utm_campaign=hackathon/); assert.match(html, /rel="noopener noreferrer"/);
    assert.match(html, locale === "en" ? /Zhihu search excerpt/ : /知乎搜索摘录/);
    assert.match(html, locale === "en" ? /formula may be missing/ : /摘录可能缺少公式/);
    assert.doesNotMatch(html, /sha256|semantic_support|全文已验证|verified fact/);
  }
});

test("untrusted source URLs cannot become clickable links", () => {
  for (const url of ["javascript:alert(1)", "https://zhihu.com.example.net/question/1", "https://user@zhihu.com/question/1", "http://zhihu.com/question/1"]) {
    assert.equal(sourceHref(url), undefined);
    const html = renderToStaticMarkup(<SourceCard card={{ ...card, original_url: url }} index={0} selected={false} selectionFull={false} onSelect={() => {}} />);
    assert.doesNotMatch(html, /href=/);
  }
  assert.equal(sourceHref(card.original_url), card.original_url);
});

test("two-source comparison presents reading questions without an inferred verdict", () => {
  const other = { ...card, span_id: "span-two", source_id: "source-two", title: "第二种条件" };
  const html = renderToStaticMarkup(<SourceComparison cards={[card, other]} comparisons={[{
    span_ids: [card.span_id, other.span_id], proposed_relation: "UNSUPPORTED_MAJORITY_VERDICT", reading_question: "两段话的定义域一致吗？", status: "unverified",
  }]} onClear={() => {}} />);
  assert.match(html, /两段话的定义域一致吗/); assert.match(html, /AI 对照问题/);
  assert.doesNotMatch(html, /UNSUPPORTED_MAJORITY_VERDICT/);
  assert.equal(renderToStaticMarkup(<SourceComparison cards={[card]} comparisons={[]} onClear={() => {}} />), "");
});

test("comparison limits disable only unselected sources", () => {
  const unselected = renderToStaticMarkup(<SourceCard card={card} index={2} selected={false} selectionFull onSelect={() => {}} />);
  const selected = renderToStaticMarkup(<SourceCard card={card} index={0} selected selectionFull onSelect={() => {}} />);
  assert.match(unselected, /type="checkbox" disabled/); assert.doesNotMatch(selected, /disabled/); assert.match(selected, /checked/);
});

test("feedback refers to the actual prior question, and explanation remains assisted learning", () => {
  const html = renderToStaticMarkup(<I18nProvider initialLocale="en"><LearningFeedback view={view} /></I18nProvider>);
  assert.match(html, /上一题：当 x = −3/); assert.match(html, /此前题目的解释/);
  assert.doesNotMatch(html, /当前题目：当 x = −2/); assert.match(html, /assisted learning recorded/);
});

test("understanding checks are usable without AI organization and never expose a model-supplied answer", () => {
  const html = renderToStaticMarkup(<I18nProvider initialLocale="en"><LearningPanel view={view} busy={false} onRespond={() => {}} onExplain={() => {}} /></I18nProvider>);
  assert.match(html, /Your answer/); assert.match(html, /inputMode="decimal"/); assert.match(html, /Show explanation/);
  assert.doesNotMatch(html, /mastered|AI 整理未能/);
  const choiceHtml = renderToStaticMarkup(<IndependentCheck check={{ ...check, response_type: "choice", choices: [{ id: "A", text: "非负值" }, { id: "B", text: "负值" }] }} busy onRespond={() => {}} onExplain={() => {}} />);
  assert.match(choiceHtml, /<fieldset[^>]*disabled/); assert.equal((choiceHtml.match(/type="radio"/g) || []).length, 2);
  assert.doesNotMatch(choiceHtml, /correct_answer|is_correct/);
});

test("initial inquiry controls and sample prompts have an English UI", () => {
  const html = renderToStaticMarkup(<I18nProvider initialLocale="en"><ExplorationWorkbench /></I18nProvider>);
  assert.match(html, /Follow a question/); assert.match(html, /What would you like to understand/);
  assert.match(html, /Why does 0.999/); assert.match(html, /Compare approaches/);
  assert.doesNotMatch(html, /你想弄清|知识探索|开始探索/);
});

test("credential controls distinguish saved and environment-managed connections", () => {
  const html = renderToStaticMarkup(<I18nProvider initialLocale="en"><ConnectionForm
    configuration={{ configured: true, has_saved_secret: true, environment_managed: true, persistent: false }}
    apiKey="" busy={false} error="" notice="" onKeyChange={() => {}} onSave={() => {}} onRemove={() => {}} /></I18nProvider>);
  assert.match(html, /type="password"/); assert.match(html, /autoComplete="off"/); assert.match(html, /environment-provided credential/);
  assert.match(html, /run only/); assert.match(html, /Remove saved credential/); assert.match(html, /not in browser storage/);
  assert.match(html, /value=""/);
});

test("a cancelled or superseded request cannot replace the current inquiry", () => {
  const owner = new ExplorationRequests(), first = owner.begin(), second = owner.begin();
  assert.equal(first.signal.aborted, true); assert.equal(owner.accepts(first), false); assert.equal(owner.accepts(second), true);
  owner.finish(first); assert.equal(owner.busy, true); assert.equal(owner.accepts(second), true);
  owner.cancel(); assert.equal(second.signal.aborted, true); assert.equal(owner.accepts(second), false); assert.equal(owner.busy, false);
});

test("mutation requests carry server revisions, language, and cancellation through authenticated fetch", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ input: RequestInfo | URL; init: RequestInit }> = [];
  globalThis.fetch = async (input, init) => { requests.push({ input, init: init || {} }); return Response.json(view); };
  const controller = new AbortController();
  try {
    await explorationApi.respond(view, check.check_id, "2", "en", controller.signal);
    await explorationApi.explain(view, check.check_id, "zh", controller.signal);
    await explorationApi.reflect(view, "我的新理解", "en", controller.signal);
    assert.deepEqual(JSON.parse(String(requests[0].init.body)), { revision: 3, language: "en", check_id: check.check_id, answer: "2" });
    assert.deepEqual(JSON.parse(String(requests[1].init.body)), { revision: 3, language: "zh", check_id: check.check_id });
    assert.deepEqual(JSON.parse(String(requests[2].init.body)), { revision: 3, language: "en", reflection: "我的新理解" });
    assert.equal(requests[2].init.method, "PUT");
    for (const request of requests) {
      assert.equal(request.init.signal, controller.signal); assert.equal(request.init.credentials, "include");
      assert.equal(new Headers(request.init.headers).get("X-MathTutor-CSRF"), "1");
      assert.equal(request.init.cache, "no-store");
      assert.doesNotMatch(String(request.init.body), /evidence|correctness|independent_successes/);
    }
  } finally { globalThis.fetch = originalFetch; }
});

test("new inquiries send a stable client identity and the list generation", async () => {
  const originalFetch = globalThis.fetch;
  let sent: unknown;
  globalThis.fetch = async (_input, init) => { sent = JSON.parse(String(init?.body)); return Response.json(view); };
  const body = { inquiry_id: view.inquiry_id, question: view.question, generation: 4, goal: view.goal, language: "zh" as const };
  try { await explorationApi.create(body, new AbortController().signal); assert.deepEqual(sent, body); }
  finally { globalThis.fetch = originalFetch; }
});

test("API conflicts retain their status and validation errors cannot echo credential inputs", async () => {
  const originalFetch = globalThis.fetch, signal = new AbortController().signal;
  try {
    globalThis.fetch = async () => Response.json({ detail: "此问题已有更新，请重新打开后继续。" }, { status: 409 });
    await assert.rejects(explorationApi.organize(view, "zh", signal), error => error instanceof ExplorationApiError && error.status === 409);
    globalThis.fetch = async () => Response.json({ detail: [{ input: "SECRET_SHOULD_NOT_RENDER", msg: "validation failed" }] }, { status: 422 });
    await assert.rejects(explorationApi.configure("some-secret", signal), error => error instanceof ExplorationApiError && !error.message.includes("SECRET_SHOULD_NOT_RENDER"));
  } finally { globalThis.fetch = originalFetch; }
});

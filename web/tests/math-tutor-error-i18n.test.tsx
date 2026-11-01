import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {I18nProvider, type Locale} from "../lib/i18n";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import type {TutorMessage} from "../features/math-tutor/types";

const errors = [
  ["请求队列已满，这条请求尚未执行。请稍后重试。", "The request queue is full. This request has not run. Please try again shortly."],
  ["已停止：这条排队请求尚未执行。如需继续，请重新发送。", "Stopped: this queued request has not run. Send it again if you want to continue."],
  ["停止请求的对话标识无效。", "The stop request has an invalid conversation identifier."],
  ["停止请求与当前生成的对话不一致。", "The stop request does not match the conversation currently generating a reply."],
  ["当前没有正在生成或排队的请求。", "There is no reply being generated or request waiting in the queue."],
  ["消息过长，请缩短后重新发送。", "This message is too long. Shorten it and send it again."],
  ["同一个请求标识对应了不同内容，请重新发送。", "This request identifier was already used for different content. Please send again."],
  ["请求尚未执行，请重试。", "This request has not run. Please try again."],
  ["这道表达式超出计算预算，请缩短式子或减小数值后重试。", "This expression exceeds the calculation limit. Shorten it or use smaller numbers and try again."],
] as const;

function render(locale: Locale, kind: TutorMessage["kind"], text: string, recover = false) {
  return renderToStaticMarkup(<I18nProvider initialLocale={locale}>
    <TutorActionCard message={{id:"message", kind, text, action:"TUTOR_CHAT", assistanceLevel:0, version:1}}
      onRecover={recover ? () => {} : undefined} />
  </I18nProvider>);
}

test("system error cards render transport and calculation errors in the selected language", () => {
  for (const [source, english] of errors) {
    for (const locale of ["zh-CN", "en"] as const) {
      const html = render(locale, "error", source, true);
      assert.match(html, /role="alert"/);
      assert.ok(html.includes(locale === "en" ? english : source), `${locale}: ${source}`);
      assert.ok(html.includes(locale === "en" ? ">Resync</button>" : ">重新同步</button>"));
      if (locale === "en") assert.ok(!html.includes(source), source);
    }
  }
});

test("unknown system errors remain readable in either language", () => {
  const original = "新的错误详情：请保留这段原文。";
  for (const locale of ["zh-CN", "en"] as const) {
    assert.ok(render(locale, "error", original).includes(original));
  }
});

test("student and model bodies retain original text even when it matches a system error key", () => {
  for (const locale of ["zh-CN", "en"] as const) {
    for (const kind of ["student", "tutor"] as const) {
      for (const [source, english] of errors) {
        const html = render(locale, kind, source);
        assert.ok(html.includes(source), `${locale}/${kind}: ${source}`);
        assert.ok(!html.includes(english));
        assert.doesNotMatch(html, /role="alert"/);
      }
    }
  }
});

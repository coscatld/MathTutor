"use client";

import {useI18n} from "@/lib/i18n";
import Link from "next/link";
import {ArrowRight, FileText, ListChecks, Quote} from "lucide-react";
import {referenceSelectionHref} from "../lib/workspace-navigation";

export default function ReferenceJourney({conversationId}: {conversationId?: string}) {
  const {t} = useI18n();
  return <section className="mt-reference-journey" aria-labelledby="reference-journey-title">
    <div className="mt-reference-intro">
      <div><p className="mt-eyebrow">{t("给讲解提供依据")}</p><h2 id="reference-journey-title">{t("资料如何进入回答")}</h2></div>
      <Link href={referenceSelectionHref(conversationId)} className="mt-btn mt-btn-ghost text-[var(--primary-text)]">
        {conversationId ? t("选择当前对话资料") : t("打开对话选择资料")}<ArrowRight className="h-4 w-4" aria-hidden="true" />
      </Link>
    </div>
    <ol className="mt-reference-steps">
      <li><span className="mt-reference-step-icon"><FileText aria-hidden="true" /></span><div><h3><span>01</span> {t(" 保存资料")}</h3><p>{t("讲义、题库与笔记保留在知识库。")}</p></div></li>
      <li><span className="mt-reference-step-icon"><ListChecks aria-hidden="true" /></span><div><h3><span>02</span> {t(" 选择参考范围")}</h3><p>{t("在“对话资料”中选择并应用，下一条消息生效。")}</p></div></li>
      <li><span className="mt-reference-step-icon"><Quote aria-hidden="true" /></span><div><h3><span>03</span> {t(" 按引用查原文")}</h3><p>{t("回答引用资料时，可打开对应版本与原文。")}</p></div></li>
    </ol>
    <p className="mt-reference-boundary">{t("保存资料不会自动开放给所有对话。")}<Link href="/math-tutor/profile">{t("学习画像")}</Link>{t("依据可核验作答形成，阅读与上传资料不会增加掌握证据。")}</p>
  </section>;
}

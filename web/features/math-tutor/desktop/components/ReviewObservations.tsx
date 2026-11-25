"use client";

import {useI18n} from "@/lib/i18n";
import {productClass} from "@/styles/product-classes";
import {makeSessionId} from "../../lib/protocol";
import {buildPracticeLaunch, tutorLaunchHref} from "../lib/question-bank";
import type {StudentSummary} from "../types";

const REASONS: Record<string, string> = {
  interval: "提交的区间与原不等式不一致。下一题检查边界、方向和端点。",
  missing_variable: "作答只给出部分未知数。下一题给出完整数对，再代回两个方程。",
  system_check: "提交的等式或数对未同时满足原方程组。下一题逐个条件代回检查。",
  missing_root: "提交的解集少了原方程的解。下一题写出每个分支。",
  extraneous_root: "提交的解中有值不满足原方程。下一题将每个候选值代回原式。",
  terms: "变形后一次项的系数发生了变化。下一题先合并同类项，再求解。",
  constant: "这次变形改变了等式的解。下一题对两边做相同的加减运算。",
  sign: "提交的值与核验结果符号相反。下一题先确定符号，再计算。",
  value: "提交的数值未通过核验。下一题写出运算顺序后再计算。",
  expression: "提交的表达式未通过原式检验。下一题展开并比较同类项。",
  answer_form: "作答中的变量或结果形式与要求不一致。下一题先核对题目要求。",
  substitution: "提交的结果未通过原方程检验。下一题求解后代回原条件。",
};
const CATEGORIES = {calculation: "计算结果", conditions: "题目条件", method_transfer: "结构变式"};
const MODES = {independent:"独立作答", assisted:"受助作答", post_solution:"答案后作答", repeat:"同题再答", choice:"选择题作答"};

export default function ReviewObservations({rows, onEvidence}: {
  rows: NonNullable<StudentSummary["review_observations"]>; onEvidence: (cycleId: string) => void;
}) {
  const {locale, t} = useI18n();
  return <section className={productClass("mt-card p-5 sm:p-6")} aria-labelledby="observed-errors-title">
    <h2 id="observed-errors-title" className="mt-section-title">{t("错题与下一道练习")}</h2>
    <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{t("分类依据是这道题的作答。要确认概念理解，还需要新的独立证据。")}</p>
    <ul className="mt-3 divide-y divide-[var(--border)]">
      {rows.map(row => <li key={row.event_id} className="space-y-2 py-4">
        <h3 className="font-medium">{t(CATEGORIES[row.category])}</h3>
        <p className="text-sm text-[var(--muted-foreground)]">{t(MODES[row.mode])} · <time dateTime={row.occurred_at}>{new Date(row.occurred_at).toLocaleDateString(locale)}</time>
          {row.corrected_later && <> · {t("原题后来答对")}</>}</p>
        <p className="text-sm leading-6">{t(REASONS[row.reason] || "结合原题记录核对本次作答。")}</p>
        {row.next_problem && <p className="break-words rounded-md bg-[var(--muted)] px-3 py-2 font-mono text-base">{row.next_problem}</p>}
        <div className={productClass("flex flex-wrap items-center gap-2")}>
          {row.next_problem && <button type="button" className={productClass("mt-btn mt-btn-primary min-h-11")}
            onClick={() => window.location.assign(tutorLaunchHref(buildPracticeLaunch({text:row.next_problem!}), makeSessionId()))}>{t("练这道变式")}</button>}
          <button type="button" className={productClass("mt-btn min-h-11")} onClick={() => onEvidence(row.cycle_id)}>{t("查看本题记录")}</button>
        </div>
      </li>)}
    </ul>
  </section>;
}

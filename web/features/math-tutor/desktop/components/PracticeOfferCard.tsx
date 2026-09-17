"use client";

import Link from "next/link";
import {ArrowRight, Loader2} from "lucide-react";
import {useState} from "react";
import {resumePractice} from "../lib/desktop-api";
import type {PracticeOffer} from "../types";

const actionClass = "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:opacity-50";
export default function PracticeOfferCard({offer, accepting, onStart, onFeedback, disabled = false}: {
  offer: PracticeOffer; accepting: boolean; onStart: () => void;
  onFeedback?: (kind: "later" | "not_relevant") => void; disabled?: boolean;
}) {
  const [resuming, setResuming] = useState(false);
  const [error, setError] = useState("");
  const active = offer.status === "ACTIVE" && offer.feedback !== "not_relevant" && Boolean(offer.offer_id?.trim()) && Boolean(offer.parent_cycle_id?.trim());
  const continuing = offer.display_status === "in_progress" && !!offer.resume_session_id;
  const completed = offer.display_status === "completed";
  return <li className={`rounded-2xl border bg-[var(--card)] p-5 sm:p-6 ${continuing ? "border-[var(--primary)]" : "border-[var(--border)]"}`}>
    <p className="text-xs font-medium text-[var(--muted-foreground)]">{continuing ? "进行中" : completed ? "已完成" : active ? (offer.feedback === "later" ? "稍后再做" : "待开始") : offer.status === "ACCEPTED" ? "已开始的历史练习" : "历史建议"}{active ? ` · ${offer.question_count ?? 1} 道题` : ""}</p>
    <h3 className="mt-3 font-serif text-xl font-semibold leading-8">{offer.title || offer.skill_labels.join("、") || "相关练习"}</h3>
    {offer.difficulty && <p className="mt-2 text-xs text-[var(--muted-foreground)]">单选题 · 练习难度 {offer.difficulty}/5（不是学生等级）</p>}
    <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{offer.reason || "围绕当前题目安排一次相关练习。"}</p>
    {!!offer.skill_labels.length && <p className="mt-2 text-xs text-[var(--muted-foreground)]">{offer.skill_labels.join(" · ")}</p>}
    {(active || continuing) && <p className="mt-3 text-sm leading-7">本次观察：{offer.observation_goal || "能否独立完成新题，哪些步骤仍需帮助。"}</p>}
    {completed && offer.result_summary && <p className="mt-3 text-sm leading-7">{offer.result_summary.observations ? `本次有 ${offer.result_summary.independent_correct} 次独立整题答对、${offer.result_summary.helped} 条受助或答案后作答记录。` : "本次练习已结束，目前没有可展示的有效作答证据。"}</p>}
    {offer.update_reason && <p className="mt-3 text-sm text-[var(--muted-foreground)]">{offer.update_reason}</p>}
    <div className="mt-5 flex flex-wrap items-center gap-2">
      {continuing ? <button disabled={resuming} className={`${actionClass} bg-[var(--primary)] text-[var(--primary-foreground)]`} onClick={async () => {setResuming(true); setError(""); try {const session = await resumePractice(offer.offer_id); window.location.href = `/math-tutor?session=${encodeURIComponent(session)}`;} catch {setError("暂时无法继续，请刷新列表后重试。"); setResuming(false);}}}>{resuming ? "正在恢复…" : "继续练习"}<ArrowRight className="h-4 w-4" aria-hidden="true" /></button> : active ? <button type="button" className={`${actionClass} bg-[var(--primary)] text-[var(--primary-foreground)]`} disabled={disabled || accepting} onClick={onStart}>{accepting ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在处理…</> : "开始练习"}</button> : null}
      {active && onFeedback && <><button className={actionClass} disabled={disabled || accepting} onClick={() => onFeedback("later")}>稍后再做</button><button className={`${actionClass} text-[var(--muted-foreground)]`} disabled={disabled || accepting} onClick={() => onFeedback("not_relevant")}>这不是我想练的</button></>}
      {completed && offer.evidence_href && <Link href={offer.evidence_href} className={`${actionClass} border border-[var(--border)] text-[var(--primary)]`}>查看学习记录</Link>}
    </div>
    {error && <p role="alert" className="mt-3 text-sm">{error}</p>}
  </li>;
}

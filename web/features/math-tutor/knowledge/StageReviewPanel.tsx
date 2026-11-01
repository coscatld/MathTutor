"use client";

import {useI18n} from "@/lib/i18n";
import {useEffect, useState} from "react";
import {knowledgeApi} from "./api";

type Review = {status:string; preferences?:{goal?:string; style?:string}; review?:null | {
  changes:{new_observations:number; removed_observations:number}; independent_correct:number; independent_incorrect:number;
  basis:Array<{event_id:string; assessment_id:string; correctness:string; evidence_kind:string}>;
  uncertain:string[]; recommendation:string; next_observation:string;
}};

export default function StageReviewPanel() {
  const {t} = useI18n();
  const [data,setData] = useState<Review|null>(null);
  const [goal,setGoal] = useState(""); const [style,setStyle] = useState("default");
  const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  const [loading,setLoading] = useState(true);
  async function load() {
    setLoading(true);setError("");
    try {const value=await knowledgeApi<Review>("/stage-review"); setData(value); setGoal(value.preferences?.goal || ""); setStyle(value.preferences?.style || "default");}
    catch {setError(t("阶段复盘暂时不可用，请稍后刷新。"));}
    finally {setLoading(false);}
  }
  useEffect(()=>{void load();},[]);
  useEffect(()=>{if(data?.status!=="pending") return; const timer=setTimeout(()=>void load(),1500); return ()=>clearTimeout(timer);},[data]);
  async function act(preferences:boolean) {
    setBusy(true);setError("");
    try {await knowledgeApi(preferences?"/stage-review/preferences":"/stage-review",preferences?{goal,style}:{},preferences?"PUT":"POST");await load();}
    catch(e){setError(e instanceof Error?e.message:t("操作未完成"));}finally{setBusy(false);}
  }
  const button="mt-btn min-h-11";
  return <section className="mt-card p-5 sm:p-6" aria-labelledby="stage-review-title">
    <h2 id="stage-review-title" className="text-lg font-semibold tracking-tight">{t("阶段学习复盘")}</h2>
    <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{t("把已验证的作答整理成阶段建议，看看变化在哪里、接下来还需要观察什么。")}</p>
    <details className="mt-4 rounded-xl border border-[var(--border)] px-4"><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">{t("学习目标与讲解偏好")}</summary><p className="mt-1 text-xs leading-6 text-[var(--muted-foreground)]">{t("你选择的目标和偏好用于安排学习，不会成为能力判断的依据。")}</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-sm">{t("当前学习目标")}<input value={goal} maxLength={240} disabled={loading || busy} onChange={e=>setGoal(e.target.value)} className="mt-input mt-2"/></label>
    <label className="text-sm">{t("你明确选择的讲解偏好")}<select value={style} disabled={loading || busy} onChange={e=>setStyle(e.target.value)} className="mt-input mt-2"><option value="default">{t("保持当前方式")}</option><option value="stepwise">{t("分步讲解")}</option><option value="concise">{t("简短提示，按需展开")}</option></select></label></div><button className={`${button} my-4`} disabled={busy || loading || !data} onClick={()=>void act(true)}>{t("保存目标与偏好")}</button></details>
    <div className="mt-4 flex flex-wrap gap-3"><button className={`${button} mt-btn-primary`} disabled={busy||loading||!data||data.status==="pending"} onClick={()=>void act(false)}>{t("复盘新观察")}</button><button className={button} disabled={busy || loading} onClick={()=>void load()}>{t("刷新复盘")}</button></div>
    {error&&<p role="alert" className="mt-3 text-sm">{error}</p>}
    {data?.status==="pending"&&<p role="status" className="mt-3 text-sm">{t("复盘已进入本地任务队列…")}</p>}
    {loading && !data && <p role="status" className="mt-4 text-sm text-[var(--muted-foreground)]">{t("正在读取阶段复盘…")}</p>}
    {data && !data.review && data.status!=="pending" && <p className="mt-4 text-sm text-[var(--muted-foreground)]">{t("还没有阶段复盘。完成作答后，点击“复盘新观察”整理这一阶段的记录。")}</p>}
    {data?.review&&<div className="mt-5 space-y-3 text-sm leading-7"><p>{t("变化：新增 {value0} 条观察，撤销 {value1} 条。独立作答答对 {value2} 次、答错 {value3} 次。", { value0: data.review.changes.new_observations, value1: data.review.changes.removed_observations, value2: data.review.independent_correct, value3: data.review.independent_incorrect })}</p>
      <p>{t("建议方式：{value0}", { value0: data.review.recommendation })}</p><p>{t("下一观察：{value0}", { value0: data.review.next_observation })}</p>
      <details><summary className="min-h-11 cursor-pointer">{t("依据与未确定事项")}</summary>{data.review.basis.map(f=><p key={f.event_id} className="break-all font-mono text-xs">{f.assessment_id} · {f.correctness} · {f.evidence_kind}</p>)}{data.review.uncertain.map(x=><p key={x}>{x}</p>)}<p>{t("待验证假设：暂无；不根据聊天次数推断能力。")}</p></details>
    </div>}
  </section>;
}

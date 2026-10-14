"use client";
import {useEffect, useState} from "react";
import {knowledgeApi} from "./api";

type Review = {status:string; preferences?:{goal?:string; style?:string}; review?:null | {
  changes:{new_observations:number; removed_observations:number}; independent_correct:number; independent_incorrect:number;
  basis:Array<{event_id:string; assessment_id:string; correctness:string; evidence_kind:string}>;
  uncertain:string[]; recommendation:string; next_observation:string;
}};

export default function StageReviewPanel() {
  const [data,setData] = useState<Review|null>(null);
  const [goal,setGoal] = useState(""); const [style,setStyle] = useState("default");
  const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  async function load() {
    try {const value=await knowledgeApi<Review>("/stage-review"); setData(value); setGoal(value.preferences?.goal || ""); setStyle(value.preferences?.style || "default");}
    catch {setError("阶段复盘暂时不可用，请稍后刷新。");}
  }
  useEffect(()=>{void load();},[]);
  useEffect(()=>{if(data?.status!=="pending") return; const timer=setTimeout(()=>void load(),1500); return ()=>clearTimeout(timer);},[data]);
  async function act(preferences:boolean) {
    setBusy(true);setError("");
    try {await knowledgeApi(preferences?"/stage-review/preferences":"/stage-review",preferences?{goal,style}:{},preferences?"PUT":"POST");await load();}
    catch(e){setError(e instanceof Error?e.message:"操作未完成");}finally{setBusy(false);}
  }
  const button="mt-btn min-h-11";
  return <section className="mt-card p-5 sm:p-6" aria-labelledby="stage-review-title">
    <h2 id="stage-review-title" className="text-lg font-semibold tracking-tight">阶段学习复盘</h2>
    <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">依据已验证学习事件整理，与 DKT 独立。当前为规则复盘，不是模型掌握度评估。</p>
    <div className="mt-4 grid gap-3 sm:grid-cols-2"><label className="text-sm">当前学习目标<input value={goal} maxLength={240} onChange={e=>setGoal(e.target.value)} className="mt-input mt-2"/></label>
    <label className="text-sm">你明确选择的讲解偏好<select value={style} onChange={e=>setStyle(e.target.value)} className="mt-input mt-2"><option value="default">保持当前方式</option><option value="stepwise">分步讲解</option><option value="concise">简短提示，按需展开</option></select></label></div>
    <div className="mt-4 flex flex-wrap gap-3"><button className={button} disabled={busy} onClick={()=>void act(true)}>保存目标与偏好</button><button className={button} disabled={busy||data?.status==="pending"} onClick={()=>void act(false)}>复盘新观察</button><button className={button} disabled={busy} onClick={()=>void load()}>刷新复盘</button></div>
    {error&&<p role="alert" className="mt-3 text-sm">{error}</p>}
    {data?.status==="pending"&&<p role="status" className="mt-3 text-sm">复盘已进入本地任务队列…</p>}
    {!data?.review&&<p className="mt-4 text-sm">尚无复盘。阅读、收藏或说“懂了”不会增加独立成功。</p>}
    {data?.review&&<div className="mt-5 space-y-3 text-sm leading-7"><p>变化：新增 {data.review.changes.new_observations} 条观察，撤销 {data.review.changes.removed_observations} 条。独立作答答对 {data.review.independent_correct} 次、答错 {data.review.independent_incorrect} 次。</p>
      <p>建议方式：{data.review.recommendation}</p><p>下一观察：{data.review.next_observation}</p>
      <details><summary className="min-h-11 cursor-pointer">依据与未确定事项</summary>{data.review.basis.map(f=><p key={f.event_id} className="break-all font-mono text-xs">{f.assessment_id} · {f.correctness} · {f.evidence_kind}</p>)}{data.review.uncertain.map(x=><p key={x}>{x}</p>)}<p>待验证假设：暂无；不根据聊天次数推断能力。</p></details>
    </div>}
  </section>;
}

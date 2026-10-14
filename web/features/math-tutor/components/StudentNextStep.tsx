"use client";

import { ArrowRight, ChartSpline, Check, CornerUpLeft, Lightbulb, PencilLine, Shapes } from "lucide-react";
import { isAcceptableOffer, offerPurposeLabel, teachingReasonLabels } from "../lib/teaching-contract";
import type { ActiveOffer, AllowedAction, EvidenceSummary, MathTutorCommand, ProblemContext, TeachingPlan } from "../types";

interface StudentNextStepProps {
  context?: ProblemContext | null;
  plan?: TeachingPlan | null;
  evidence?: EvidenceSummary | null;
  offer?: ActiveOffer | null;
  actions?: AllowedAction[];
  allowed: string[];
  busy: boolean;
  disabled: boolean;
  onWrite: () => void;
  onCommand: (command: MathTutorCommand, payload?: Record<string, string>) => void;
}

/** The public capability snapshot, when present, overrides legacy inputs. */
export function studentActionEnabled(command: MathTutorCommand, actions: AllowedAction[] | undefined, allowed: string[]): boolean {
  return actions === undefined ? allowed.includes(command) : actions.some(action => action.command === command && action.enabled);
}

export function studentStepGuidance(plan?: TeachingPlan | null, evidence?: EvidenceSummary | null): string {
  if (plan?.student_guidance?.trim()) return plan.student_guidance;
  const reason = teachingReasonLabels(plan?.reason_codes || []).find(text => !text.includes("当前的小目标"));
  if (reason) return reason;
  if (evidence?.post_solution) return "刚才看过解答。可以用一道新题，检查能不能自己用上这个方法。";
  if (evidence?.assisted && !evidence.independent) return "刚才有提示帮忙。接下来可以试一道新题，看看自己能写到哪一步。";
  return "先写出你能确定的一步。卡住时，选一点提示或看相关例题的示范。";
}

const controls = [
  { command: "request_hint", label: "提示", Icon: Lightbulb },
  { command: "submit_attempt", label: "我来写", Icon: PencilLine },
  { command: "request_example", label: "看一步", Icon: Shapes },
  { command: "request_practice", label: "再来一道", Icon: ArrowRight },
] as const;

export default function StudentNextStep({ context, plan, evidence, offer, actions, allowed, busy, disabled, onWrite, onCommand }: StudentNextStepProps) {
  const hasAction = (command: MathTutorCommand) => actions === undefined ? allowed.includes(command) : actions.some(action => action.command === command);
  const enabled = (command: MathTutorCommand) => !busy && !disabled && studentActionEnabled(command, actions, allowed);
  const validOffer = isAcceptableOffer(offer);
  const active = context?.lifecycle.toUpperCase() === "ACTIVE";
  const ended = ["CLOSED", "ENDED", "SKIPPED"].includes(context?.lifecycle.toUpperCase() || "");
  const checking = context?.understanding_check === true;
  if (!context && !validOffer) {
    const navigation = [
      { command: "resume_problem" as const, label: "回到原题" },
      { command: "skip_diagnostic" as const, label: "跳过检查，回到原题" },
    ].filter(action => studentActionEnabled(action.command, actions, allowed));
    if (!navigation.length) return null;
    return <section aria-label="返回原题" className="mt-student-step">
      <h2 className="text-sm font-semibold">检查题尚未准备好，回到原题继续。</h2>
      <div className="mt-student-step-actions">{navigation.map(action => <button key={action.command} type="button" className="mt-step-button" disabled={!enabled(action.command)} onClick={() => { if (enabled(action.command)) onCommand(action.command); }}><CornerUpLeft className="h-4 w-4" aria-hidden="true" />{action.label}</button>)}</div>
    </section>;
  }
  const visible = controls.filter(control => hasAction(control.command));
  const unavailable = [...new Set(visible.flatMap(control => actions?.find(action => action.command === control.command && !action.enabled)?.description || []))];
  const canSelfReport = active && studentActionEnabled("submit_attempt", actions, allowed);
  const goal = ended ? "可以在下面输入一道新题，继续一起练习。" : active ? plan?.question_goal || context?.current_subgoal?.prompt_target : "把这个方法用在一道新题上，看看能不能自己完成。";

  return <section aria-label="下一步学习" className="mt-student-step">
    <div className="mt-student-step-heading"><PencilLine className="h-4 w-4" aria-hidden="true" /><h2>{checking ? "用一道小题检查一下" : ended ? "这道题先到这里" : active ? "轮到你写" : "接下来，自己试一道"}</h2></div>
    {goal ? <p className="mt-student-step-goal">{goal}</p> : null}
    {!ended ? <p className="mt-student-step-guidance">{studentStepGuidance(active ? plan : null, evidence)}</p> : null}
    <div className="mt-student-step-actions">
      {visible.map(({ command, label, Icon }) => {
        const capability = actions?.find(action => action.command === command);
        const available = enabled(command);
        return <button key={command} type="button" disabled={!available} aria-describedby={!available && capability?.description ? "next-step-unavailable" : undefined} title={command === "request_example" && available ? "看相关例题的解题示范" : capability?.description || undefined} className={`mt-step-button ${command === "submit_attempt" ? "mt-step-button-primary" : ""}`} onClick={() => {
          if (!available) return;
          if (command === "submit_attempt") onWrite();
          else onCommand(command);
        }}><Icon className="h-4 w-4" aria-hidden="true" />{command === "submit_attempt" && context?.choices ? "我来选" : label}</button>;
      })}
      {active && context?.graphable && !checking ? <button type="button" disabled={busy || disabled} className="mt-step-button" title="画出这道题对应的函数图像" onClick={() => { if (!busy && !disabled) onCommand("send_message", { text: "画出这道题的函数图像" }); }}><ChartSpline className="h-4 w-4" aria-hidden="true" />看图像</button> : null}
      {canSelfReport && !checking ? <button type="button" disabled={busy || disabled} className="mt-step-button" onClick={() => { if (!busy && !disabled) onCommand("send_message", { text: "我懂了" }); }}><Check className="h-4 w-4" aria-hidden="true" />我懂了，检查一下</button> : null}
      {hasAction("resume_problem") ? <button type="button" className="mt-step-button" disabled={!enabled("resume_problem")} onClick={() => { if (enabled("resume_problem")) onCommand("resume_problem"); }}><CornerUpLeft className="h-4 w-4" aria-hidden="true" />回到原题</button> : null}
      {checking && hasAction("skip_diagnostic") ? <button type="button" className="mt-step-button" disabled={!enabled("skip_diagnostic")} onClick={() => { if (enabled("skip_diagnostic")) onCommand("skip_diagnostic"); }}>跳过检查，回到原题</button> : null}
    </div>
    {unavailable.length ? <p id="next-step-unavailable" className="mt-3 text-xs leading-5 text-[var(--muted-foreground)]">{unavailable.join(" ")}</p> : null}
    {validOffer ? <div className="mt-inline-practice" aria-label="下一道练习">
      <div><p className="text-sm font-semibold">{offerPurposeLabel(offer.purpose)}</p><p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">{offer.title || "用一道新题继续练习。"}</p></div>
      <div className="mt-student-step-actions">
        {hasAction("accept_practice_offer") ? <button type="button" className="mt-step-button mt-step-button-primary" disabled={!enabled("accept_practice_offer")} onClick={() => { if (enabled("accept_practice_offer")) onCommand("accept_practice_offer", { offer_id: offer.offer_id }); }}>开始这道练习<ArrowRight className="h-4 w-4" aria-hidden="true" /></button> : null}
        {hasAction("decline_practice_offer") ? <button type="button" className="mt-step-button" disabled={!enabled("decline_practice_offer")} onClick={() => { if (enabled("decline_practice_offer")) onCommand("decline_practice_offer", { offer_id: offer.offer_id }); }}>先留在这题</button> : null}
      </div>
    </div> : null}
  </section>;
}

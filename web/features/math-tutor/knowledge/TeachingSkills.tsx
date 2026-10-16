"use client";

import { Loader2, RefreshCw, Wand2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export type TeachingSkill = {id: string; name: string; description: string; enabled: boolean; source: string; activation?: string};

/** The shared server catalog is read only for its teaching-method projection. */
export function teachingSkills(value: unknown): TeachingSkill[] {
  if (!value || typeof value !== "object" || !Array.isArray((value as {skills?: unknown}).skills)) throw new Error("教学技能暂时没有读取完整，请重试。");
  return ((value as {skills: unknown[]}).skills).map(row => {
    if (!row || typeof row !== "object") throw new Error("教学技能暂时没有读取完整，请重试。");
    const skill = row as Record<string, unknown>;
    if (typeof skill.id !== "string" || typeof skill.name !== "string" || typeof skill.description !== "string" || typeof skill.enabled !== "boolean") throw new Error("教学技能暂时没有读取完整，请重试。");
    return {id: skill.id, name: skill.name, description: skill.description, enabled: skill.enabled,
      source: typeof skill.source === "string" ? skill.source : "configured", ...(typeof skill.activation === "string" ? {activation: skill.activation} : {})};
  });
}

export function TeachingSkillsList({skills}: {skills: TeachingSkill[]}) {
  return skills.length ? <div className="grid gap-4 md:grid-cols-2">{skills.map(skill => <article key={skill.id} className="mt-card space-y-3 p-5"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{skill.name}</h3><span className="mt-tool-badge" data-tone={skill.enabled ? "active" : undefined}>{skill.enabled ? skill.activation || "可用" : "未启用"}</span></div><p className="text-sm leading-7 text-[var(--muted-foreground)]">{skill.description}</p><p className="text-xs text-[var(--muted-foreground)]">{skill.source === "builtin" ? "应用内置" : "当前应用提供"}</p></article>)}</div> : <p className="mt-card p-5 text-sm leading-7 text-[var(--muted-foreground)]">当前没有提供教学技能。你仍可以整理资料和进行数学辅导。</p>;
}

export default function TeachingSkills() {
  const [skills, setSkills] = useState<TeachingSkill[] | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await apiFetch("/api/v2/math-tutor/desktop/creator/catalog");
      if (!response.ok) throw new Error("教学技能暂时无法读取，请重试。");
      setSkills(teachingSkills(await response.json()));
    } catch (cause) { setSkills(null); setError(cause instanceof Error ? cause.message : "教学技能暂时无法读取，请重试。"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return <section className="space-y-5" aria-label="教学技能">
    <div className="mt-card flex items-start gap-4 p-5 sm:p-6"><span className="mt-tool-heading-icon"><Wand2 className="h-5 w-5" aria-hidden="true" /></span><div><h2 className="text-lg font-semibold">帮助理解问题的教学方法</h2><p className="mt-2 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">这里展示当前应用提供的教学方法，辅导时会根据问题需要使用。你的题库和笔记继续在资料页管理。</p></div></div>
    {error ? <div className="mt-knowledge-alert" role="alert"><p>{error}</p><button type="button" className="mt-btn min-h-11" disabled={loading} onClick={() => void refresh()}><RefreshCw className="h-4 w-4" aria-hidden="true" />重新读取</button></div> : null}
    {loading ? <p role="status" className="mt-tool-loading"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在读取教学技能…</p> : skills ? <TeachingSkillsList skills={skills} /> : null}
  </section>;
}

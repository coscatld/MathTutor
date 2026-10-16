"use client";

import { Download, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { BEFORE_TUTOR_NAVIGATION, requestTutorNavigation } from "../lib/navigation-guard";
import { communityApi, downloadCommunityJson, permissionLabel, type Permission, type PluginPackage } from "./api";

type Props = {busy: boolean; action: (work: () => Promise<void>) => Promise<void>; notice: (value: string) => void};
const workflowNames = {"exam-builder": "组一套练习题", "mistake-review": "整理错题", "learning-report": "查看学习变化"};

export function pluginCommunityBundle(plugin: PluginPackage, hash: string) {
  return {format: "mathtutor.community-resource.v1", resource: {
    metadata: {id: plugin.id, version: plugin.version, type: "plugin", name: plugin.name, author: plugin.author,
      license: plugin.license, description: plugin.description, tags: plugin.tags, grades: plugin.grades,
      readme: plugin.readme, changelog: plugin.changelog, permissions: plugin.required_permissions, package_sha256: hash},
    package: {filename: `${plugin.id}-${plugin.version}.json`, media_type: "application/json", data: plugin},
  }};
}

export default function PluginCreator({busy, action, notice}: Props) {
  const [templates, setTemplates] = useState<PluginPackage[]>([]), [template, setTemplate] = useState<PluginPackage | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(""), [reload, setReload] = useState(0), [dirty, setDirty] = useState(false);
  const [name, setName] = useState(""), [author, setAuthor] = useState(""), [license, setLicense] = useState("Apache-2.0");
  const [version, setVersion] = useState("1.0.0"), [description, setDescription] = useState(""), [tags, setTags] = useState(""), [audience, setAudience] = useState("all");
  const [readme, setReadme] = useState(""), [guidance, setGuidance] = useState(""), [config, setConfig] = useState<Record<string, unknown>>({}), [changelog, setChangelog] = useState("首次分享。");
  const errorRef = useRef<HTMLParagraphElement>(null), packageId = useRef<string | null>(null);
  useEffect(() => {
    let live = true; setLoading(true); setError("");
    void communityApi<{items: PluginPackage[]}>("/plugins/examples").then(value => {
      if (!live) return;
      setTemplates(value.items);
      const first = value.items[0];
      if (!first) throw new Error("当前应用尚未提供可创建的插件模板。");
      setTemplate(first); setConfig({...first.defaults}); setGuidance(first.teaching_guidance); setReadme(first.readme);
    }).catch(cause => { if (live) setError(cause instanceof Error ? cause.message : "插件模板暂时无法读取。"); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [reload]);
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    const guard = (event: Event) => { if (!window.confirm("插件还有未保存的修改，确认离开？")) event.preventDefault(); };
    const navigate = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!target || target.download || target.target === "_blank") return;
      const next = new URL(target.href, window.location.href);
      if (next.pathname === window.location.pathname && next.search === window.location.search && next.origin === window.location.origin) return;
      if (!requestTutorNavigation()) { event.preventDefault(); event.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload); window.addEventListener(BEFORE_TUTOR_NAVIGATION, guard); document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", unload); window.removeEventListener(BEFORE_TUTOR_NAVIGATION, guard); document.removeEventListener("click", navigate, true); };
  }, [dirty]);
  const edit = (setter: (value: string) => void) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => { setter(event.target.value); setDirty(true); };
  const configure = (key: string, value: unknown) => { setConfig(previous => ({...previous, [key]: value})); setDirty(true); };
  const fail = (message: string) => { setError(message); window.requestAnimationFrame(() => errorRef.current?.focus()); };
  const permissions: Permission[] = template ? [...template.required_permissions] : [];
  if (template?.workflow === "exam-builder" && config.focus_weak_skills && !permissions.includes("read_learning_records")) permissions.push("read_learning_records");
  const submit = () => {
    if (!template) return;
    packageId.current ??= `custom.${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
    const gradeValues = audience === "all" ? [] : audience === "primary" ? [1,2,3,4,5,6] : audience === "middle" ? [7,8,9] : [10,11,12];
    const payload = {...template, id: packageId.current, name: name.trim(), author: author.trim(), license: license.trim(), version: version.trim(),
      description: description.trim(), tags: tags.split(/[,，]/).map(value => value.trim()).filter(Boolean), grades: gradeValues,
      readme, teaching_guidance: guidance, changelog, defaults: config, required_permissions: permissions};
    setError("");
    void action(async () => {
      try {
        const result = await communityApi<{package: PluginPackage; package_hash: string}>("/plugins/validate", {package: payload});
        downloadCommunityJson(pluginCommunityBundle(result.package, result.package_hash), `${result.package.id}-${result.package.version}.mathtutor`);
        setDirty(false); notice("插件已保存到下载文件夹。将文件分享给他人，对方可在社区直接导入；你也可以导入后试用。");
      } catch (cause) { fail(cause instanceof Error ? cause.message : "插件暂时无法保存，填写的内容已保留。"); }
    });
  };
  const numberField = (label: string, key: string, min: number, max: number) => <label className="mt-field">{label}<input className="mt-input min-h-11" type="number" min={min} max={max} step={1} required value={typeof config[key] === "number" ? config[key] as number : ""} disabled={busy} onChange={event => configure(key, event.target.value === "" ? "" : Number(event.target.value))} /></label>;
  const checkbox = (label: string, key: string) => <label className="community-check community-full"><input type="checkbox" checked={Boolean(config[key])} disabled={busy} onChange={event => configure(key, event.target.checked)} />{label}</label>;
  return <section className="community-stack" aria-label="创建教学插件">
    <div><h2>把你的教学方法分享出去</h2><p className="community-muted mt-2">选一种用途，填写名称和使用说明，就能保存为别人可以直接导入的插件。</p></div>
    {error ? <p ref={errorRef} tabIndex={-1} role="alert" className="community-alert">{error}{!template ? <button type="button" className="mt-btn min-h-11" onClick={() => setReload(value => value + 1)}><RefreshCw className="h-4 w-4" aria-hidden="true" />重新读取模板</button> : null}</p> : null}
    {loading ? <p role="status" className="mt-tool-loading"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在读取可用模板…</p> : template ? <form className="community-publish" onSubmit={event => { event.preventDefault(); submit(); }}>
      <label className="mt-field community-full">你想做什么<select className="mt-input min-h-11" value={template.workflow} disabled={busy} onChange={event => {
        const next = templates.find(item => item.workflow === event.target.value);
        if (!next || (dirty && !window.confirm("切换用途会重置练习设置和使用说明，名称与作者信息会保留。确认切换？"))) return;
        packageId.current = null;
        setTemplate(next); setConfig({...next.defaults}); setGuidance(next.teaching_guidance); setReadme(next.readme); setDirty(true);
      }}>{templates.map(item => <option key={item.id} value={item.workflow}>{workflowNames[item.workflow]}</option>)}</select></label>
      <label className="mt-field">插件名称<input className="mt-input min-h-11" value={name} required maxLength={80} placeholder="例如：我的每周练习" disabled={busy} onChange={edit(setName)} /></label>
      <label className="mt-field">作者署名<input className="mt-input min-h-11" value={author} required maxLength={120} placeholder="你希望展示的名字" disabled={busy} onChange={edit(setAuthor)} /></label>
      <label className="mt-field community-full">它能帮大家做什么<textarea className="mt-input min-h-24" value={description} required maxLength={500} disabled={busy} onChange={edit(setDescription)} /></label>
      {template.workflow === "exam-builder" ? <>
        <label className="mt-field">练习年级<select className="mt-input min-h-11" value={String(config.grade)} disabled={busy} onChange={event => configure("grade", Number(event.target.value))}>{Array.from({length: 12}, (_, index) => <option key={index + 1} value={index + 1}>{index + 1} 年级</option>)}</select></label>
        {numberField("每套题目数量", "question_count", 1, 20)}
        {checkbox("附上参考答案，方便练习后核对", "include_answers")}
        {checkbox("优先练习常出错的知识点（需要读取作答记录）", "focus_weak_skills")}
      </> : template.workflow === "mistake-review" ? <>
        {numberField("每次整理多少条错题", "limit", 1, 30)}
        {checkbox("包含获得提示后的作答", "include_assisted")}
        {checkbox("包含部分答对的记录", "include_partial")}
      </> : <>
        {numberField("每组练习数量", "window_size", 5, 100)}
        {numberField("参考最近多少条学习记录", "max_events", 10, 1000)}
      </>}
      <div className="community-permission-summary community-full"><h3><ShieldCheck className="mr-2 inline h-4 w-4" aria-hidden="true" />使用时需要的数据</h3><ul>{permissions.map(permission => <li key={permission}>{permissionLabel(permission)}</li>)}</ul><p>使用者导入后，会先看到这些说明，再自行同意并启用。</p></div>
      <label className="mt-field community-full">使用说明<textarea className="mt-input min-h-40" value={readme} required maxLength={12000} disabled={busy} onChange={edit(setReadme)} /></label>
      <label className="mt-field community-full">教学建议<textarea className="mt-input min-h-24" value={guidance} maxLength={2000} placeholder="例如：先请学生独立尝试，再讨论关键步骤。" disabled={busy} onChange={edit(setGuidance)} /><small className="community-muted">分享给使用者的教学建议。</small></label>
      <details className="community-full"><summary className="min-h-11 cursor-pointer">分享设置</summary><div className="community-publish mt-3">
        <label className="mt-field">适合的学习阶段<select className="mt-input min-h-11" value={audience} disabled={busy} onChange={edit(setAudience)}><option value="all">不限</option><option value="primary">小学</option><option value="middle">初中</option><option value="high">高中</option></select></label>
        <label className="mt-field">标签<input className="mt-input min-h-11" value={tags} maxLength={396} placeholder="例如：每周练习，复习" disabled={busy} onChange={edit(setTags)} /></label>
        <label className="mt-field">版本<input className="mt-input min-h-11" value={version} required pattern="(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})" maxLength={14} disabled={busy} onChange={edit(setVersion)} /></label>
        <label className="mt-field">允许他人如何使用<select className="mt-input min-h-11" value={license} disabled={busy} onChange={edit(setLicense)}><option value="Apache-2.0">允许使用、修改和分享（Apache 2.0）</option><option value="MIT">宽松开源（MIT）</option></select></label>
        <label className="mt-field community-full">本次更新说明<textarea className="mt-input min-h-24" value={changelog} required maxLength={8000} disabled={busy} onChange={edit(setChangelog)} /></label>
      </div></details>
      <div className="community-full community-actions"><button className="mt-btn mt-btn-primary min-h-11" disabled={busy}><Download className="h-4 w-4" aria-hidden="true" />保存插件</button></div>
    </form> : null}
  </section>;
}

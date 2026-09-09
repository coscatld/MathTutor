"use client";

import { Cloud, Database, Download, KeyRound, Loader2, RefreshCw, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  deleteLocalEmbeddingModel,
  DesktopApiError,
  downloadLocalEmbeddingModel,
  fetchEmbeddingSettings,
  removeEmbeddingApiKey,
  saveEmbeddingSettings,
  testEmbeddingConnection,
} from "../lib/desktop-api";
import type { EmbeddingProvider, EmbeddingSettings } from "../types";
import EmbeddingStatusBadge from "./EmbeddingStatusBadge";
import { useToast } from "./ToastProvider";

export interface EmbeddingSettingsPanelProps {
  fetchFn?: typeof fetchEmbeddingSettings;
  saveFn?: typeof saveEmbeddingSettings;
  downloadFn?: typeof downloadLocalEmbeddingModel;
  deleteFn?: typeof deleteLocalEmbeddingModel;
  removeKeyFn?: typeof removeEmbeddingApiKey;
  testFn?: typeof testEmbeddingConnection;
}

export default function EmbeddingSettingsPanel({
  fetchFn = fetchEmbeddingSettings,
  saveFn = saveEmbeddingSettings,
  downloadFn = downloadLocalEmbeddingModel,
  deleteFn = deleteLocalEmbeddingModel,
  removeKeyFn = removeEmbeddingApiKey,
  testFn = testEmbeddingConnection,
}: EmbeddingSettingsPanelProps) {
  const toast = useToast();
  const [settings, setSettings] = useState<EmbeddingSettings | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState<EmbeddingProvider>("local");
  const [localModel, setLocalModel] = useState("bge-small-zh-v1.5");
  const [baseUrl, setBaseUrl] = useState("");
  const [cloudModel, setCloudModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState<"save" | "download" | "delete" | "test" | "key" | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const apply = useCallback((next: EmbeddingSettings) => {
    setSettings(next);
    setEnabled(next.enabled);
    setProvider(next.provider);
    setLocalModel(next.local_model_id);
    setBaseUrl(next.cloud_base_url);
    setCloudModel(next.cloud_model);
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await fetchFn());
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof DesktopApiError ? error.message : "读取 Embedding 设置失败。" });
    }
  }, [apply, fetchFn]);

  useEffect(() => { load().catch(() => undefined); }, [load]);
  useEffect(() => {
    if (settings?.local_download_status !== "downloading") return;
    const timer = window.setInterval(() => load().catch(() => undefined), 1200);
    return () => window.clearInterval(timer);
  }, [load, settings?.local_download_status]);

  const save = async () => {
    setBusy("save");
    setMessage(null);
    try {
      const next = await saveFn({
        enabled,
        provider,
        local_model_id: localModel,
        cloud_base_url: baseUrl.trim(),
        cloud_model: cloudModel.trim(),
        cloud_api_key: apiKey.trim() || undefined,
      });
      apply(next);
      setApiKey("");
      const text = enabled ? "资料检索设置已保存。" : "Embedding 已关闭，继续使用关键词检索。";
      setMessage({ kind: "ok", text });
      toast({ title: text, tone: "success" });
    } catch (error) {
      const text = error instanceof DesktopApiError ? error.message : "保存失败，请稍后重试。";
      setMessage({ kind: "error", text });
      toast({ title: "保存失败", description: text, tone: "error" });
    } finally { setBusy(null); }
  };

  const download = async () => {
    setBusy("download");
    setMessage(null);
    try {
      apply(await downloadFn(localModel));
      setMessage({ kind: "ok", text: "已开始从 ModelScope 下载，离开此页不会中断。" });
      toast({ title: "本地模型开始下载", description: "离开此页不会中断。", tone: "info" });
    } catch (error) {
      const text = error instanceof DesktopApiError ? error.message : "无法开始下载。";
      setMessage({ kind: "error", text });
      toast({ title: "无法开始下载", description: text, tone: "error" });
    } finally { setBusy(null); }
  };

  const removeLocal = async () => {
    setBusy("delete");
    try {
      apply(await deleteFn(localModel));
      setMessage({ kind: "ok", text: "本地模型已删除，检索已回退到关键词。" });
      toast({ title: "本地模型已删除", description: "资料检索已回退到关键词。", tone: "success" });
    } catch (error) {
      const text = error instanceof DesktopApiError ? error.message : "删除失败。";
      setMessage({ kind: "error", text });
      toast({ title: "删除失败", description: text, tone: "error" });
    } finally { setBusy(null); }
  };

  const removeKey = async () => {
    setBusy("key");
    try {
      apply(await removeKeyFn());
      setApiKey("");
      setMessage({ kind: "ok", text: "云端 API Key 已从系统凭据库移除。" });
      toast({ title: "云端 API Key 已移除", tone: "success" });
    } catch (error) {
      const text = error instanceof DesktopApiError ? error.message : "移除失败。";
      setMessage({ kind: "error", text });
      toast({ title: "移除失败", description: text, tone: "error" });
    } finally { setBusy(null); }
  };

  const test = async () => {
    setBusy("test");
    try {
      const result = await testFn();
      setMessage({ kind: result.ok ? "ok" : "error", text: result.message });
      toast({ title: result.ok ? "Embedding 连接成功" : "Embedding 连接失败", description: result.message, tone: result.ok ? "success" : "error" });
      if (result.ok) await load();
    } catch (error) {
      const text = error instanceof DesktopApiError ? error.message : "连接测试失败。";
      setMessage({ kind: "error", text });
      toast({ title: "Embedding 连接失败", description: text, tone: "error" });
    } finally { setBusy(null); }
  };

  if (!settings) {
    return <div className="flex min-h-32 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] text-sm text-[var(--muted-foreground)]"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在加载资料检索设置…</div>;
  }

  const downloadLabels = { not_downloaded: "未下载", downloading: "下载中", ready: "已就绪", failed: "下载失败" } as const;
  const selectedModel = settings.local_models.find((item) => item.model_id === localModel);

  return (
    <section className="overflow-hidden rounded-2xl border border-[#D7D0C2] bg-[#FBF8F1] shadow-sm dark:border-slate-700 dark:bg-slate-900" aria-label="资料检索 / Embedding">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#E5DED1] px-5 py-4 dark:border-slate-700">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold tracking-wide text-[#735B2B] dark:text-amber-300"><Search className="h-4 w-4" />资料检索 / Embedding</p>
          <p className="mt-1 max-w-lg text-sm leading-relaxed text-[#6F675A] dark:text-slate-400">给资料增加语义匹配。关闭或配置不完整时，关键词检索始终可用。</p>
        </div>
        <EmbeddingStatusBadge settings={settings} />
      </div>

      <div className="flex flex-col gap-5 p-5">
        <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-[#DED5C6] bg-white/70 p-4 dark:border-slate-700 dark:bg-slate-950/40">
          <span><span className="block text-sm font-semibold text-[var(--foreground)]">启用 Embedding 检索</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">默认关闭；只有你开启后才会下载模型或调用云端。</span></span>
          <input className="peer sr-only" type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          <span className="relative h-7 w-12 shrink-0 rounded-full bg-slate-300 transition peer-checked:bg-[#B56B32] peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[#B56B32] after:absolute after:left-1 after:top-1 after:h-5 after:w-5 after:rounded-full after:bg-white after:shadow after:transition-transform peer-checked:after:translate-x-5" aria-hidden="true" />
        </label>

        {enabled ? (
          <div className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Embedding 模型来源">
              {([['local', Database, '本地模型', '下载一次，之后可离线使用'], ['cloud', Cloud, '云端模型', '使用 OpenAI 兼容接口']] as const).map(([value, Icon, title, detail]) => (
                <label key={value} className={`flex min-h-[76px] cursor-pointer items-center gap-3 rounded-xl border p-3 text-left transition ${provider === value ? "border-[#B56B32] bg-[#FFF3DE] ring-1 ring-[#B56B32]/20 dark:bg-amber-950/30" : "border-[#DED5C6] bg-white/60 hover:border-[#B9A98C] dark:border-slate-700 dark:bg-slate-950/30"}`}>
                  <span className={`grid h-9 w-9 place-items-center rounded-full ${provider === value ? "bg-[#B56B32] text-white" : "bg-[#EEE8DC] text-[#735B2B] dark:bg-slate-800 dark:text-slate-300"}`}><Icon className="h-4 w-4" /></span>
                  <span><span className="block text-sm font-semibold text-[var(--foreground)]">{title}</span><span className="mt-0.5 block text-xs text-[var(--muted-foreground)]">{detail}</span></span>
                  <input type="radio" name="embedding-provider" value={value} checked={provider === value} onChange={() => setProvider(value)} className="ml-auto h-4 w-4 accent-[#B56B32]" />
                </label>
              ))}
            </div>

            {provider === "local" ? (
              <div className="rounded-xl border border-[#DED5C6] bg-white/70 p-4 dark:border-slate-700 dark:bg-slate-950/30">
                <p className="text-sm font-semibold text-[var(--foreground)]">选择本地模型</p>
                <div className="mt-3 flex flex-col gap-2">
                  {settings.local_models.map((item) => (
                    <label key={item.model_id} className="flex cursor-pointer items-start gap-3 rounded-lg border border-[#E8E1D5] p-3 dark:border-slate-700">
                      <input type="radio" name="local-embedding-model" value={item.model_id} checked={localModel === item.model_id} onChange={() => setLocalModel(item.model_id)} className="mt-1 accent-[#B56B32]" />
                      <span className="flex-1"><span className="block text-sm font-medium text-[var(--foreground)]">{item.label}</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">{item.size_label} · {item.dimension} 维 · 下载源 {item.source}</span></span>
                    </label>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs"><span className="rounded-full bg-[#EEE8DC] px-2.5 py-1 font-medium text-[#735B2B] dark:bg-slate-800 dark:text-slate-300">{downloadLabels[settings.local_download_status]}</span>{selectedModel ? <span className="text-[var(--muted-foreground)]">保存到应用用户数据目录，不进入项目仓库</span> : null}</div>
                {settings.local_download_status === "downloading" ? <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#E8E1D5]"><div className="h-full w-2/5 animate-pulse rounded-full bg-[#B56B32]" /></div> : null}
                {settings.local_download_error ? <p className="mt-2 text-xs text-red-600">{settings.local_download_error}</p> : null}
                <div className="mt-4 flex gap-2">
                  {settings.local_download_status !== "ready" ? <button type="button" onClick={download} disabled={busy !== null || settings.local_download_status === "downloading"} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[#B56B32] px-3 text-sm font-medium text-white disabled:opacity-50">{settings.local_download_status === "downloading" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}下载到本地</button> : <button type="button" onClick={removeLocal} disabled={busy !== null} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-red-200 px-3 text-sm font-medium text-red-600"><Trash2 className="h-4 w-4" />删除本地权重</button>}
                </div>
              </div>
            ) : (
              <div className="grid gap-3 rounded-xl border border-[#DED5C6] bg-white/70 p-4 dark:border-slate-700 dark:bg-slate-950/30">
                <label className="text-sm font-medium text-[var(--foreground)]">API Base URL<input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" className="mt-1.5 h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 font-normal" /></label>
                <label className="text-sm font-medium text-[var(--foreground)]">API Key<div className="relative mt-1.5"><KeyRound className="absolute left-3 top-3.5 h-4 w-4 text-[var(--muted-foreground)]" /><input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings.cloud_key_masked ? `已保存：${settings.cloud_key_masked}（留空保持）` : "仅保存到系统安全凭据库"} className="h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] pl-10 pr-3 font-normal" /></div></label>
                <label className="text-sm font-medium text-[var(--foreground)]">Model Name<input type="text" value={cloudModel} onChange={(event) => setCloudModel(event.target.value)} placeholder="例如 text-embedding-3-small" className="mt-1.5 h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 font-normal" /></label>
                <div className="flex flex-wrap gap-2"><button type="button" onClick={test} disabled={busy !== null || !settings.cloud_has_api_key} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--border)] px-3 text-sm font-medium disabled:opacity-50">{busy === "test" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}测试连接</button>{settings.cloud_has_api_key ? <button type="button" onClick={removeKey} disabled={busy !== null} className="min-h-10 px-2 text-sm font-medium text-red-600">移除云端 Key</button> : null}</div>
              </div>
            )}
          </div>
        ) : null}

        {enabled && settings.reindex_required ? <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">模型或来源已变化，旧向量不会参与检索。请到“我的数据”执行“重建派生索引”；重建前自动回退关键词结果。</p> : null}
        {message ? <p role="status" className={`rounded-lg px-3 py-2 text-sm ${message.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{message.text}</p> : null}
        <button type="button" onClick={save} disabled={busy !== null} className="inline-flex min-h-11 w-fit items-center gap-2 rounded-xl bg-[#2E2922] px-4 text-sm font-semibold text-white transition hover:bg-black disabled:opacity-50 dark:bg-amber-200 dark:text-slate-950">{busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}保存检索设置</button>
      </div>
    </section>
  );
}

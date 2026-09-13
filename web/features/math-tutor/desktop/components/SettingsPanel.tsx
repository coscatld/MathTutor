"use client";

import { CheckCircle2, ChevronDown, CircleHelp, KeyRound, Loader2, PlugZap, RefreshCw, Settings2, ShieldAlert, Sparkles, TriangleAlert, WifiOff, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  DesktopApiError,
  fetchModels,
  fetchPresets,
  fetchSettings,
  modelErrorCopy,
  removeApiKey,
  saveSettings,
  testModelConnection,
} from "../lib/desktop-api";
import type {
  DesktopSettings,
  ModelErrorKind,
  ModelTestResult,
  ProviderPreset,
  TestConnectionResult,
} from "../types";
import ConversationTrashPanel from "./ConversationTrashPanel";
import BackupPanel from "./BackupPanel";
import DataPrivacySettings from "./DataPrivacySettings";
import EmbeddingSettingsPanel from "./EmbeddingSettingsPanel";
import DocumentsPanel from "./DocumentsPanel";
import MemoryPanel from "./MemoryPanel";
import TutorPersonalityPanel from "./TutorPersonalityPanel";
import { useToast } from "./ToastProvider";

export interface FormMessage {
  kind: "ok" | "error";
  text: string;
}

export interface SettingsFormData {
  visionMode?: "auto" | "enabled" | "disabled";
  presets: ProviderPreset[];
  settings: DesktopSettings | null;
  presetId: string;
  apiKey: string;
  baseUrl: string;
  model: string;
  keyMasked: string | null;
  advancedOpen: boolean;
  models: string[] | null;
  saving: boolean;
  testing: boolean;
  discovering: boolean;
  removing: boolean;
  confirmingRemoval: boolean;
  testResult: TestConnectionResult | null;
  message: FormMessage | null;
}

export interface SettingsFormHandlers {
  onVisionModeChange?: (mode: "auto" | "enabled" | "disabled") => void;
  onPresetChange: (presetId: string) => void;
  onApiKeyChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onToggleAdvanced: () => void;
  onDiscoverModels: () => void;
  onSave: (e: React.FormEvent) => void;
  onTest: () => void;
  onAskRemove: () => void;
  onCancelRemove: () => void;
  onRemove: () => void;
}

/**
 * Presentational settings form. The API key is held in React state only and
 * sent via PUT /settings; the masked tail returned by the backend is the only
 * key material ever shown. No browser storage is touched.
 */
export function SettingsForm({ data, handlers }: { data: SettingsFormData; handlers: SettingsFormHandlers }) {
  const currentPreset = data.presets.find((p) => p.preset_id === data.presetId) ?? null;
  const providerSaved = data.settings?.preset_id === data.presetId;
  const formSaved = providerSaved && !data.apiKey.trim() && data.model === (data.settings?.model ?? "") && data.baseUrl === (data.settings?.base_url ?? "");
  const canTest = formSaved && (data.visionMode ?? "auto") === (data.settings?.vision_mode ?? "auto") && (currentPreset?.local ? Boolean(data.baseUrl.trim()) : Boolean(data.settings?.is_configured));
  const connectionLabel = !providerSaved ? "未保存" : data.testing ? "正在连接" : data.settings?.connection_status === "success" ? "连接成功" : data.settings?.connection_status === "failure" ? "连接失败" : data.settings?.is_configured ? "已配置" : "未配置";

  return (
    <form
      onSubmit={handlers.onSave}
      className="flex flex-col gap-5 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm"
      aria-label="AI 模型设置"
    >
      <div className="flex items-center justify-between gap-3"><div><h3 className="font-serif text-lg font-bold">生成模型</h3><p className="mt-1 text-xs text-slate-500">用于 Tutor 表达与练习候选生成；数学验证仍由确定性后端完成。</p></div><span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${connectionLabel === "连接成功" ? "bg-emerald-100 text-emerald-700" : connectionLabel === "连接失败" ? "bg-rose-100 text-rose-700" : "bg-slate-100 text-slate-600"}`}>{connectionLabel}</span></div>
      {/* Provider */}
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium text-[var(--foreground)]">模型服务商</span>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="模型服务商">
          {data.presets.map((preset) => {
            const selected = preset.preset_id === data.presetId;
            return (
              <button
                key={preset.preset_id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => handlers.onPresetChange(preset.preset_id)}
                className={`inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] ${
                  selected
                    ? "border-[#2563EB] bg-[#2563EB]/10 text-[#1D4ED8] dark:text-blue-400"
                    : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--ring)]"
                }`}
              >
                <span className="flex flex-col items-start"><span>{preset.label}</span>{preset.local ? <span className="text-[10px] font-normal opacity-60">本地运行</span> : null}</span>
                {preset.custom && <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* API key — password input, never echoes the full key */}
      {currentPreset?.requires_api_key !== false ? <div className="flex flex-col gap-2">
        <label htmlFor="settings-apikey" className="text-sm font-medium text-[var(--foreground)]">
          API 密钥
        </label>
        <div className="flex flex-col gap-1.5">
          <div className="relative">
            <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" aria-hidden="true" />
            <input
              id="settings-apikey"
              type="password"
              autoComplete="off"
              placeholder={data.keyMasked ? `已保存：${data.keyMasked}（留空则保持不变）` : "粘贴 API 密钥"}
              value={data.apiKey}
              onChange={(e) => handlers.onApiKeyChange(e.target.value)}
              className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] pl-10 pr-3 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
            />
          </div>
          <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
            {data.keyMasked
              ? `当前密钥尾号 ${data.keyMasked}。密钥保存在系统安全凭据存储中，不会在界面或浏览器存储中回显。`
              : "密钥仅保存在系统安全凭据存储中，不会保存在浏览器存储里。"}
          </p>
          {providerSaved && data.keyMasked ? (
            data.confirmingRemoval ? (
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
                <span className="mr-auto">移除后将立即回到模板教学，学习数据不会被删除。</span>
                <button type="button" onClick={handlers.onCancelRemove} disabled={data.removing} className="min-h-[40px] rounded-lg px-3 font-medium hover:bg-white/60">
                  取消
                </button>
                <button type="button" onClick={handlers.onRemove} disabled={data.removing} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg bg-red-600 px-3 font-medium text-white disabled:opacity-50">
                  {data.removing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                  确认移除
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={handlers.onAskRemove}
                className="min-h-[40px] w-fit text-sm font-medium text-red-600 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] dark:text-red-400"
              >
                移除已保存的 API Key
              </button>
            )
          ) : null}
        </div>
      </div> : <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300">Ollama 在本机运行，不需要 API Key。</div>}

      {/* Custom / advanced foldout */}
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={handlers.onToggleAdvanced}
          aria-expanded={data.advancedOpen}
          className="inline-flex min-h-[40px] w-fit cursor-pointer items-center gap-1.5 text-sm font-medium text-[#1D4ED8] dark:text-blue-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
        >
          {currentPreset?.custom ? "自定义模型" : "高级选项"}
          <ChevronDown className={`h-4 w-4 transition-transform duration-200 ${data.advancedOpen ? "rotate-180" : ""}`} aria-hidden="true" />
        </button>
        {data.advancedOpen && (
          <div className="flex flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="settings-baseurl" className="text-sm font-medium text-[var(--foreground)]">
                服务地址（Base URL）
              </label>
              <input
                id="settings-baseurl"
                type="text"
                autoComplete="off"
                placeholder={currentPreset?.local ? "http://127.0.0.1:11434" : currentPreset?.custom ? "https://…（必填）" : "使用服务商默认地址"}
                value={data.baseUrl}
                onChange={(e) => handlers.onBaseUrlChange(e.target.value)}
                readOnly={!currentPreset?.editable_base_url}
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] read-only:cursor-default read-only:bg-[var(--muted)] read-only:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
              />
              <p className="text-xs text-[var(--muted-foreground)]">默认使用服务商地址，可修改。API Key 将发送到此地址，请仅填写可信服务。</p>
              {currentPreset?.base_url && <button type="button" onClick={() => handlers.onBaseUrlChange(currentPreset.base_url!)} className="w-fit text-xs text-blue-600">恢复默认地址</button>}
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="settings-model" className="text-sm font-medium text-[var(--foreground)]">
                模型名称
              </label>
              <input
                id="settings-model"
                type="text"
                autoComplete="off"
                placeholder={currentPreset?.custom ? "例如 deepseek-chat（必填）" : "使用服务商默认模型"}
                value={data.model}
                onChange={(e) => handlers.onModelChange(e.target.value)}
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
              />
            </div>
            {(currentPreset?.custom || currentPreset?.local) && (
              <button
                type="button"
                onClick={handlers.onDiscoverModels}
                disabled={data.discovering || !providerSaved}
                className="inline-flex min-h-[44px] w-fit cursor-pointer items-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {data.discovering ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
                {currentPreset?.local ? "读取本机模型" : "发现可用模型"}
              </button>
            )}
            <label className="flex flex-col gap-2 text-sm font-medium">
              图片输入能力
              <select value={data.visionMode ?? "auto"} onChange={(event) => handlers.onVisionModeChange?.(event.target.value as "auto" | "enabled" | "disabled")} className="h-11 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3">
                <option value="auto">自动识别（默认）</option>
                <option value="enabled">启用（已确认模型支持视觉）</option>
                <option value="disabled">关闭（纯文本模型）</option>
              </select>
              <span className="text-xs font-normal text-[var(--muted-foreground)]">未识别的视觉模型或自定义别名可选择启用。仅适用于兼容图片输入的服务；此选项不会让纯文本模型获得视觉能力。</span>
            </label>
            {(currentPreset?.custom || currentPreset?.local) && !providerSaved ? <p className="text-xs text-[var(--muted-foreground)]">先保存当前服务商，再读取可用模型。</p> : null}
            {data.models !== null && data.models.length > 0 && (
              <ul className="flex flex-wrap gap-2" aria-label="发现到的模型">
                {data.models.map((m) => (
                  <li key={m}><button type="button" onClick={() => handlers.onModelChange(m)} className={`rounded-full border px-3 py-1.5 text-xs ${data.model === m ? "border-[#2563EB] bg-[#2563EB]/10 text-[#1D4ED8]" : "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]"}`}>{m}</button></li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-3 border-t border-[var(--border)] pt-4">
        {data.message && (
          <p
            role="status"
            className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${
              data.message.kind === "ok"
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400"
            }`}
          >
            {data.message.kind === "ok" ? <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" /> : null}
            {data.message.text}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            disabled={data.saving}
            className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl bg-[#2563EB] px-5 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {data.saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {data.saving ? "保存中…" : "保存设置"}
          </button>
          <button
            type="button"
            onClick={handlers.onTest}
            disabled={data.testing || !canTest}
            className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] px-5 py-2 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {data.testing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <PlugZap className="h-4 w-4" aria-hidden="true" />}
            测试连接
          </button>
        </div>
      </div>
    </form>
  );
}

const MODEL_ERROR_ICONS: Record<ModelErrorKind, typeof ShieldAlert> = {
  response_incomplete: TriangleAlert,
  request_rejected: XCircle,
  quota_exceeded: ShieldAlert,
  rate_limited: RefreshCw,
  provider_error: TriangleAlert,
  credential_invalid: KeyRound,
  network_unavailable: WifiOff,
  provider_unsupported: CircleHelp,
  model_unavailable: XCircle,
  gateway_disabled: ShieldAlert,
};

/**
 * Five-kind model connection result card. Maps ``error_kind`` onto distinct
 * friendly copy and a suggested action; renders the backend's friendly
 * ``message`` as plain text. NEVER raw HTTP tracebacks / Authorization
 * headers / API keys / internal stacks.
 */
export function ModelTestCard({ result }: { result: ModelTestResult }) {
  if (result.ok) {
    return (
      <p
        role="status"
        className="flex flex-col gap-0.5 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
      >
        <span className="flex items-center gap-1.5 font-medium">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          连接成功，模型可正常调用
        </span>
        {result.message ? <span className="text-xs opacity-90">{result.message}</span> : null}
      </p>
    );
  }

  const copy = modelErrorCopy(result.error_kind);
  const ErrorIcon = result.error_kind ? (MODEL_ERROR_ICONS[result.error_kind] ?? TriangleAlert) : TriangleAlert;
  return (
    <div
      role="status"
      className="flex flex-col gap-1 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400"
    >
      <span className="flex items-center gap-1.5 font-medium">
        <ErrorIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {copy.title}
      </span>
      {result.message ? <span>{result.message}</span> : null}
      <span className="text-xs opacity-90">{copy.advice}</span>
    </div>
  );
}

interface Props {
  /** Injectable fetchers — defaults hit the desktop bridge (tests pass fakes). */
  fetchSettingsFn?: typeof fetchSettings;
  fetchPresetsFn?: typeof fetchPresets;
  saveSettingsFn?: typeof saveSettings;
  testModelConnectionFn?: typeof testModelConnection;
  fetchModelsFn?: typeof fetchModels;
  removeApiKeyFn?: typeof removeApiKey;
}

/**
 * 设置 → AI 模型。The API key lives in React state only while this panel is
 * mounted, is sent exclusively via PUT /settings, and is never echoed back —
 * the UI shows the masked tail returned by the backend. Nothing here touches
 * localStorage/sessionStorage/IndexedDB.
 */
export default function SettingsPanel({
  fetchSettingsFn = fetchSettings,
  fetchPresetsFn = fetchPresets,
  saveSettingsFn = saveSettings,
  testModelConnectionFn = testModelConnection,
  fetchModelsFn = fetchModels,
  removeApiKeyFn = removeApiKey,
}: Props) {
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [presetId, setPresetId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [visionMode, setVisionMode] = useState<"auto" | "enabled" | "disabled">("auto");
  const [model, setModel] = useState("");
  const [keyMasked, setKeyMasked] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [models, setModels] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const [modelTest, setModelTest] = useState<ModelTestResult | null>(null);
  const [message, setMessage] = useState<FormMessage | null>(null);
  const [section, setSection] = useState<"general" | "model" | "tutor" | "data" | "appearance" | "advanced" | "trash">("model");
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, s] = await Promise.all([fetchPresetsFn(), fetchSettingsFn()]);
      setPresets(p);
      setSettings(s);
      setVisionMode(s.vision_mode ?? "auto");
      setPresetId(s.preset_id);
      setBaseUrl(s.base_url || p.find((preset) => preset.preset_id === s.preset_id)?.base_url || "");
      setModel(s.model);
      setKeyMasked(s.key_masked);
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "读取设置失败，请稍后再试。",
      });
    } finally {
      setLoading(false);
    }
  }, [fetchPresetsFn, fetchSettingsFn]);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const currentPreset = presets.find((p) => p.preset_id === presetId) ?? null;
    if (!currentPreset) return;
    setSaving(true);
    setMessage(null);
    try {
      const result = await saveSettingsFn({
        preset_id: currentPreset.preset_id,
        vision_mode: visionMode,
        api_key: apiKey.trim() || undefined,
        base_url: currentPreset.editable_base_url ? baseUrl.trim() : undefined,
        model: model.trim() || undefined,
      });
      setKeyMasked(result.key_masked);
      setApiKey("");
      setBaseUrl(result.base_url);
      setModel(result.model);
      setVisionMode(result.vision_mode ?? "auto");
      setSettings((current) => current ? {
        ...current,
        preset_id: result.preset_id,
        vision_mode: result.vision_mode ?? "auto",
        base_url: result.base_url,
        model: result.model,
        is_configured: result.is_configured,
        onboarding_completed: result.onboarding_completed,
        key_masked: result.key_masked,
        provider_configs: {
          ...(current.provider_configs ?? {}),
          [result.preset_id]: {
            vision_mode: result.vision_mode ?? "auto",
            model: result.model,
            base_url: result.base_url,
            has_api_key: Boolean(result.key_masked),
            key_masked: result.key_masked,
          },
        },
      } : current);
      setMessage({ kind: "ok", text: currentPreset.local ? "Ollama 设置已保存。" : currentPreset.custom ? "自定义模型已保存并生效。" : "模型设置已保存并生效。" });
      toast({ title: "模型设置已保存", description: "Tutor 将在下一轮请求中使用这套配置。" });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "保存失败，请稍后再试。",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setModelTest(null);
    try {
      const result = await testModelConnectionFn();
      setModelTest(result);
      if (result.ok && result.resolved_model) setModel(result.resolved_model);
      setSettings((current) => current ? {
        ...current,
        connection_status: result.ok ? "success" : "failure",
        is_configured: result.ok ? true : current.is_configured,
        model: result.ok && result.resolved_model ? result.resolved_model : current.model,
        provider_configs: result.ok && result.resolved_model ? {
          ...(current.provider_configs ?? {}),
          [current.preset_id]: {
            model: result.resolved_model,
            base_url: current.base_url,
            has_api_key: Boolean(current.key_masked),
            key_masked: current.key_masked,
          },
        } : current.provider_configs,
      } : current);
      toast({ title: result.ok ? "模型连接成功" : "模型连接失败", description: result.message || (result.ok ? "配置可以使用。" : "请检查密钥、网络和模型名称。"), tone: result.ok ? "success" : "error" });
    } catch (err) {
      setModelTest({
        ok: false,
        error_kind: null,
        message: err instanceof DesktopApiError ? err.message : "连接测试失败。",
      });
    } finally {
      setTesting(false);
    }
  };

  const handleDiscover = async () => {
    setDiscovering(true);
    try {
      setModels(await fetchModelsFn());
    } catch (err) {
      setModels(null);
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "模型发现失败，请稍后再试。",
      });
    } finally {
      setDiscovering(false);
    }
  };

  const handleRemove = async () => {
    setRemoving(true);
    setMessage(null);
    try {
      const next = await removeApiKeyFn();
      setSettings(next);
      setKeyMasked(null);
      setApiKey("");
      setModelTest(null);
      setConfirmingRemoval(false);
      setMessage({ kind: "ok", text: "API Key 已移除，已切换为模板教学。" });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "移除失败，请稍后再试。",
      });
    } finally {
      setRemoving(false);
    }
  };

  const modelPanel = loading ? (
        <div className="flex min-h-[240px] items-center justify-center text-sm text-[var(--muted-foreground)]">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
          正在加载设置…
        </div>
      ) : (
        <SettingsForm
          data={{
            presets,
            settings,
            presetId,
            apiKey,
            baseUrl,
            visionMode,
            model,
            keyMasked,
            advancedOpen,
            models,
            saving,
            testing,
            discovering,
            removing,
            confirmingRemoval,
            testResult: null,
            message,
          }}
          handlers={{
            onPresetChange: (id) => {
              const preset = presets.find((item) => item.preset_id === id);
              const profile = settings?.provider_configs?.[id];
              setPresetId(id);
              setVisionMode(profile?.vision_mode ?? "auto");
              setApiKey("");
              setBaseUrl(profile?.base_url ?? preset?.base_url ?? "");
              setModel(profile?.model ?? preset?.default_model ?? "");
              setKeyMasked(profile?.key_masked ?? (id === settings?.preset_id ? settings?.key_masked ?? null : null));
              setModels(null);
              if (preset?.local) setAdvancedOpen(true);
              setMessage(null);
              setModelTest(null);
            },
            onApiKeyChange: setApiKey,
            onBaseUrlChange: setBaseUrl,
            onModelChange: (value) => { setModel(value); setVisionMode("auto"); },
            onVisionModeChange: setVisionMode,
            onToggleAdvanced: () => setAdvancedOpen((v) => !v),
            onDiscoverModels: handleDiscover,
            onSave: handleSave,
            onTest: handleTest,
            onAskRemove: () => setConfirmingRemoval(true),
            onCancelRemove: () => setConfirmingRemoval(false),
            onRemove: handleRemove,
          }}
        />
      );
  const sections = [
    ["general", "通用"], ["model", "模型与 API"], ["tutor", "Tutor"], ["data", "数据与隐私"], ["appearance", "外观"], ["advanced", "高级"], ["trash", "垃圾桶"],
  ] as const;
  return (
    <div className="mt-settings-layout">
      <aside className="mt-settings-nav"><h1 className="mb-5 flex items-center gap-2 px-2 font-serif text-lg font-bold"><Settings2 className="h-5 w-5 text-[#1d5fd1]" />设置</h1><nav aria-label="设置分类" className="space-y-1">{sections.map(([id, label]) => <button key={id} type="button" aria-current={section === id ? "page" : undefined} onClick={() => setSection(id)} className={`w-full rounded-lg px-3 py-2 text-left text-sm ${section === id ? "bg-[var(--card)] font-semibold text-[var(--primary)] shadow-sm" : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"}`}>{label}</button>)}</nav></aside>
      <div className="mt-settings-content"><div className="mx-auto max-w-4xl">
      {section === "trash" ? <ConversationTrashPanel /> : null}
      {section === "general" ? <section><h2 className="font-serif text-xl font-bold">通用</h2><div className="mt-4 rounded-2xl border border-[#deddd7] bg-white p-5 dark:border-slate-700 dark:bg-slate-900"><p className="text-sm font-semibold">开箱即用</p><p className="mt-2 text-sm leading-6 text-slate-500">Embedding 与 OCR 等增强能力默认关闭；未配置模型时，核心练习、模板辅导和关键词检索仍可使用。</p></div></section> : null}
      {section === "model" ? <div className="space-y-4"><div><h2 className="font-serif text-xl font-bold">模型与 API</h2><p className="mt-1 text-sm text-slate-500">配置生成模型和可选的资料 Embedding。密钥只进入系统安全凭据存储。</p></div>{modelPanel}{modelTest ? <ModelTestCard result={modelTest} /> : null}{settings && !settings.is_configured && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-400">
          尚未配置 AI 模型 —— 核心练习功能不受影响，配置后可解锁个性化辅导与推荐练习。
        </p>
      )}<EmbeddingSettingsPanel /></div> : null}
      {section === "tutor" ? <TutorPersonalityPanel /> : null}
      {section === "data" ? <DataPrivacySettings /> : null}
      {section === "appearance" ? <section><h2 className="font-serif text-xl font-bold">外观</h2><div className="mt-4 rounded-2xl border border-[#deddd7] bg-white p-5 text-sm leading-6 text-slate-500 dark:border-slate-700 dark:bg-slate-900">界面跟随应用主题，并使用适合长时间学习的暖白画布与高对比文字。</div></section> : null}
      {section === "advanced" ? <div className="space-y-4"><div><h2 className="font-serif text-xl font-bold">高级</h2><p className="mt-1 text-sm text-slate-500">备份、恢复与维护操作。</p></div><BackupPanel /></div> : null}
      </div></div>
    </div>
  );
}

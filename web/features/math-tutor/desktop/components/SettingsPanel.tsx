"use client";

import { CheckCircle2, ChevronDown, CircleHelp, KeyRound, Loader2, PlugZap, RefreshCw, Settings2, ShieldAlert, Sparkles, TriangleAlert, WifiOff, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  DesktopApiError,
  fetchModels,
  fetchPresets,
  fetchSettings,
  modelErrorCopy,
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
import BackupPanel from "./BackupPanel";

export interface FormMessage {
  kind: "ok" | "error";
  text: string;
}

export interface SettingsFormData {
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
  testResult: TestConnectionResult | null;
  message: FormMessage | null;
}

export interface SettingsFormHandlers {
  onPresetChange: (presetId: string) => void;
  onApiKeyChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onToggleAdvanced: () => void;
  onDiscoverModels: () => void;
  onSave: (e: React.FormEvent) => void;
  onTest: () => void;
}

/**
 * Presentational settings form. The API key is held in React state only and
 * sent via PUT /settings; the masked tail returned by the backend is the only
 * key material ever shown. No browser storage is touched.
 */
export function SettingsForm({ data, handlers }: { data: SettingsFormData; handlers: SettingsFormHandlers }) {
  const currentPreset = data.presets.find((p) => p.preset_id === data.presetId) ?? null;

  return (
    <form
      onSubmit={handlers.onSave}
      className="flex flex-col gap-5 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm"
      aria-label="AI 模型设置"
    >
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
                {preset.label}
                {preset.custom && <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* API key — password input, never echoes the full key */}
      <div className="flex flex-col gap-2">
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
              ? `当前密钥尾号 ${data.keyMasked}。密钥加密保存在本机安全存储中，不会在界面或浏览器存储中回显。`
              : "密钥仅加密保存在本机安全存储（钥匙串）中，不会保存在浏览器存储里。"}
          </p>
        </div>
      </div>

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
                placeholder={currentPreset?.custom ? "https://…（必填）" : "使用服务商默认地址"}
                value={data.baseUrl}
                onChange={(e) => handlers.onBaseUrlChange(e.target.value)}
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
              />
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
            {currentPreset?.custom && (
              <button
                type="button"
                onClick={handlers.onDiscoverModels}
                disabled={data.discovering}
                className="inline-flex min-h-[44px] w-fit cursor-pointer items-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {data.discovering ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
                发现可用模型
              </button>
            )}
            {data.models !== null && data.models.length > 0 && (
              <ul className="flex flex-wrap gap-2" aria-label="发现到的模型">
                {data.models.map((m) => (
                  <li key={m} className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs text-[var(--foreground)]">
                    {m}
                  </li>
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
            disabled={data.testing || !data.settings?.is_configured}
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
}: Props) {
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [presetId, setPresetId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [keyMasked, setKeyMasked] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [models, setModels] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [modelTest, setModelTest] = useState<ModelTestResult | null>(null);
  const [message, setMessage] = useState<FormMessage | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, s] = await Promise.all([fetchPresetsFn(), fetchSettingsFn()]);
      setPresets(p);
      setSettings(s);
      setPresetId(s.preset_id);
      setBaseUrl(s.base_url);
      setModel(s.model);
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
        api_key: apiKey.trim() || undefined,
        base_url: currentPreset.custom ? baseUrl.trim() : undefined,
        model: currentPreset.custom ? model.trim() : undefined,
      });
      setKeyMasked(result.key_masked);
      setApiKey("");
      setBaseUrl(result.base_url);
      setModel(result.model);
      setMessage({ kind: "ok", text: currentPreset.custom ? "自定义模型已保存并生效。" : "模型设置已保存并生效。" });
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
      setModelTest(await testModelConnectionFn());
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

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-6 md:px-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-[var(--foreground)]">
          <Settings2 className="h-5 w-5 text-[#2563EB]" aria-hidden="true" />
          设置
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">配置 AI 模型后即可使用个性化辅导与自动练习邀请。</p>
      </div>

      {loading ? (
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
            model,
            keyMasked,
            advancedOpen,
            models,
            saving,
            testing,
            discovering,
            testResult: null,
            message,
          }}
          handlers={{
            onPresetChange: (id) => {
              setPresetId(id);
              setMessage(null);
              setModelTest(null);
            },
            onApiKeyChange: setApiKey,
            onBaseUrlChange: setBaseUrl,
            onModelChange: setModel,
            onToggleAdvanced: () => setAdvancedOpen((v) => !v),
            onDiscoverModels: handleDiscover,
            onSave: handleSave,
            onTest: handleTest,
          }}
        />
      )}

      {modelTest ? <ModelTestCard result={modelTest} /> : null}

      {settings && !settings.is_configured && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-400">
          尚未配置 AI 模型 —— 核心练习功能不受影响，配置后可解锁个性化辅导与自动练习邀请。
        </p>
      )}

      {/* 设置页 → 数据备份（restore 二次确认在 BackupPanel 内完成）。 */}
      <BackupPanel />
    </div>
  );
}

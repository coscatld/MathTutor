"use client";

import {
  ArrowRight,
  BookOpenCheck,
  Check,
  ChevronDown,
  KeyRound,
  Loader2,
  LockKeyhole,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  DesktopApiError,
  fetchPresets,
  fetchSettings,
  saveSettings,
  skipProviderOnboarding,
} from "../lib/desktop-api";
import type { DesktopSettings, ProviderPreset } from "../types";
import katex from "katex";
import BrandMark from "@/components/common/BrandMark";

const WORKED_STEPS = [
  { tex: "2x + 3 = 11", note: "题目" },
  { tex: "2x = 11 - 3 = 8", note: "两边减 3" },
  { tex: "x = 4", note: "两边除以 2" },
  { tex: "2 \\times 4 + 3 = 11", note: "代回核验" },
].map(step => ({ ...step, html: katex.renderToString(step.tex, { throwOnError: false, output: "html" }) }));

/** Dedicated first-run product onboarding. Secret input never leaves memory. */
export default function ProviderOnboarding() {
  const router = useRouter();
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [presetId, setPresetId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [error, setError] = useState("");

  const currentPreset = useMemo(
    () => presets.find((preset) => preset.preset_id === presetId) ?? null,
    [presetId, presets],
  );
  const keepingExistingKey = Boolean(
    settings?.is_configured &&
      settings.preset_id === presetId &&
      settings.key_masked,
  );
  const requiresApiKey = currentPreset?.requires_api_key !== false;

  useEffect(() => {
    (async () => {
      try {
        const [available, current] = await Promise.all([
          fetchPresets(),
          fetchSettings(),
        ]);
        if (current.is_configured || current.onboarding_completed) {
          router.replace(current.initial_assessment_required ? "/onboarding/assessment" : "/math-tutor");
          return;
        }
        setPresets(available);
        setSettings(current);
        setPresetId(current.preset_id || available[0]?.preset_id || "");
        setBaseUrl(current.base_url || available.find((preset) => preset.preset_id === (current.preset_id || available[0]?.preset_id))?.base_url || "");
        setModel(current.model);
      } catch {
        setError("暂时无法读取本地配置，请稍后重试。");
      } finally {
        setLoading(false);
      }
    })().catch(() => undefined);
  }, [router]);

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    if (!currentPreset) {
      setError("请选择一个模型服务商。");
      return;
    }
    if (requiresApiKey && !apiKey.trim() && !keepingExistingKey) {
      setError("请填写 API Key，或选择“暂时跳过”使用模板教学。");
      return;
    }
    if (currentPreset.custom && !baseUrl.trim()) {
      setError("自定义服务商需要填写 API 地址。");
      return;
    }
    setSaving(true);
    try {
      const saved = await saveSettings({
        preset_id: currentPreset.preset_id,
        api_key: apiKey.trim() || undefined,
        base_url: currentPreset.editable_base_url ? baseUrl.trim() : undefined,
        model: model.trim() || undefined,
      });
      setApiKey("");
      router.replace(saved.initial_assessment_required ? "/onboarding/assessment" : "/math-tutor");
    } catch (reason) {
      setError(
        reason instanceof DesktopApiError
          ? reason.message
          : "保存失败，请检查后重试。",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSkipping(true);
    setError("");
    try {
      await skipProviderOnboarding();
      router.replace("/math-tutor");
    } catch (reason) {
      setError(
        reason instanceof DesktopApiError
          ? reason.message
          : "暂时无法保存该选择，请稍后重试。",
      );
    } finally {
      setSkipping(false);
    }
  };

  return (
    <main className="mt-onboarding relative h-screen overflow-y-auto bg-[var(--background)] text-[var(--foreground)]">
      <div className="mt-onboarding-field mt-paper pointer-events-none absolute inset-0" aria-hidden="true" />

      <div className="relative mx-auto grid min-h-full w-full max-w-6xl items-center gap-12 px-6 py-10 lg:grid-cols-[0.9fr_1.1fr] lg:px-10">
        <section className="hidden lg:block" aria-label="MathTutor 介绍">
          <div className="flex items-center gap-2.5"><span className="mt-brand-mark"><BrandMark /></span><span className="mt-wordmark">Math<span>Tutor</span></span></div>
          <h2 className="mt-10 max-w-md text-[44px] font-bold leading-[1.12] tracking-[-0.035em]">
            把好奇心，
            <span className="block">变成<em className="mt-hero-em">一步步</em>的解题思路</span>
          </h2>
          <p className="mt-5 max-w-sm text-[15px] leading-7 text-[var(--muted-foreground)]">先自己尝试，卡住时再逐级获得提示。每一步都由本地求解器核验，而不只是看起来对。</p>
          <ol className="mt-worked mt-paper" aria-label="示例：逐步核验">
            {WORKED_STEPS.map((step, index) => <li key={step.note} style={{ animationDelay: `${300 + index * 420}ms` }}>
              <span className="mt-worked-index">{index + 1}</span>
              <span className="mt-worked-tex" dangerouslySetInnerHTML={{ __html: step.html }} />
              <span className="mt-worked-note"><Check className="h-3.5 w-3.5" aria-hidden="true" />{step.note}</span>
            </li>)}
          </ol>
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-[var(--muted-foreground)]">
            {["学习记录保存在本机", "提示分级，不直接给答案", "随时可以换模型"].map(item => <li key={item} className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]" aria-hidden="true" />{item}</li>)}
          </ul>
        </section>

        <section className="mt-rise mx-auto w-full max-w-2xl rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[var(--shadow-xl)] md:p-9">
          <div className="flex items-start gap-4">
            <div className="mt-empty-mark shrink-0">
              <BookOpenCheck className="h-6 w-6" aria-hidden="true" />
            </div>
            <div>
              <p className="text-sm font-semibold text-[var(--primary-text)]">欢迎使用 MathTutor</p>
              <h1 className="mt-1 text-[28px] font-bold leading-tight tracking-[-0.025em] text-[var(--foreground)]">
                配置你的 AI 数学辅导模型
              </h1>
              <p className="mt-3 max-w-xl text-sm leading-6 text-[var(--muted-foreground)]">
                选择云端服务商并填写 API Key，或使用本机 Ollama。学习记录、资料和个人记忆始终保存在这台电脑上。
              </p>
            </div>
          </div>

          {loading ? (
            <div className="flex min-h-72 items-center justify-center text-sm text-[var(--muted-foreground)]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              正在加载本地配置…
            </div>
          ) : (
            <form onSubmit={handleSave} className="mt-8 space-y-6" aria-label="AI 模型首次配置">
              <fieldset>
                <legend className="text-sm font-semibold text-[var(--foreground)]">选择模型服务商</legend>
                <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  {presets.map((preset) => {
                    const selected = preset.preset_id === presetId;
                    return (
                      <button
                        key={preset.preset_id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => {
                          setPresetId(preset.preset_id);
                          const profile = settings?.provider_configs?.[preset.preset_id];
                          setBaseUrl(profile?.base_url ?? preset.base_url ?? "");
                          setModel(profile?.model ?? preset.default_model ?? "");
                          setError("");
                          if (preset.custom || preset.local) setAdvancedOpen(true);
                        }}
                        className={`relative min-h-[52px] whitespace-nowrap rounded-xl border py-2.5 pl-3 pr-7 text-left text-sm font-semibold transition duration-200 active:scale-[.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] ${
                          selected
                            ? "border-[var(--primary)] bg-[var(--primary-soft)] text-[var(--primary-text)] shadow-[0_0_0_3px_var(--focus-halo)]"
                            : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--primary-border)] hover:bg-[var(--primary-soft)]"
                        }`}
                      >
                        {preset.label}
                        {selected ? (
                          <Check className="absolute right-2 top-2 h-3.5 w-3.5" aria-hidden="true" />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              {requiresApiKey ? <div>
                <label htmlFor="onboarding-api-key" className="text-sm font-semibold text-[var(--foreground)]">
                  API Key
                </label>
                <div className="relative mt-2">
                  <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" aria-hidden="true" />
                  <input
                    id="onboarding-api-key"
                    type="password"
                    autoComplete="off"
                    required={!keepingExistingKey}
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder={keepingExistingKey ? `已保存：${settings?.key_masked}` : "粘贴你的 API Key"}
                    className="h-12 w-full rounded-xl border border-[var(--input)] bg-[var(--card)] pl-11 pr-4 text-sm text-[var(--foreground)] shadow-[var(--shadow-xs)] outline-none transition placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)] focus:ring-4 focus:ring-[var(--focus-halo)]"
                  />
                </div>
                <p className="mt-2 flex items-center gap-1.5 text-xs leading-5 text-[var(--muted-foreground)]">
                  <LockKeyhole className="h-3.5 w-3.5 text-[var(--primary-text)]" aria-hidden="true" />
                  API Key 使用系统安全凭据存储，不会写入学习数据库或浏览器存储。
                </p>
              </div> : <p className="rounded-xl bg-[var(--success-soft)] px-4 py-3 text-sm text-[var(--success)]">Ollama 在本机运行，不需要 API Key。</p>}

              <div>
                <button
                  type="button"
                  onClick={() => setAdvancedOpen((open) => !open)}
                  aria-expanded={advancedOpen}
                  className="inline-flex min-h-[40px] items-center gap-1.5 text-sm font-semibold text-[var(--primary-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                >
                  {currentPreset?.custom ? "自定义模型设置" : "高级选项"}
                  <ChevronDown className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`} aria-hidden="true" />
                </button>
                {advancedOpen ? (
                  <div className="mt-2 grid gap-3 rounded-2xl border border-[var(--border)] bg-[var(--secondary)] p-4 sm:grid-cols-2">
                    <label className="text-xs font-semibold text-[var(--muted-foreground)]">
                      服务地址 {currentPreset?.custom ? "（必填）" : "（默认已填，可修改）"}
                      <input
                        type="url"
                        value={baseUrl}
                        onChange={(event) => setBaseUrl(event.target.value)}
                        disabled={!currentPreset?.editable_base_url}
                        placeholder="https://api.example.com/v1"
                        className="mt-1.5 h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 font-normal outline-none focus:border-[var(--primary)] disabled:opacity-55"
                      />
                    </label>
                    <label className="text-xs font-semibold text-[var(--muted-foreground)]">
                      模型名称（可选）
                      <input
                        type="text"
                        value={model}
                        onChange={(event) => setModel(event.target.value)}
                        placeholder="留空则自动发现"
                        className="mt-1.5 h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 font-normal outline-none focus:border-[var(--primary)] disabled:opacity-55"
                      />
                    </label>
                  </div>
                ) : null}
              </div>

              {error ? (
                <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-[var(--destructive)] dark:border-red-900 dark:bg-red-950/40">
                  {error}
                </p>
              ) : null}

              <div className="flex flex-col gap-3 border-t border-[var(--border)] pt-5 sm:flex-row sm:items-center">
                <button
                  type="submit"
                  disabled={saving || skipping}
                  className="mt-btn mt-btn-primary min-h-[48px] flex-1"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                  {saving ? "正在安全保存…" : "保存并继续"}
                  {!saving ? <ArrowRight className="h-4 w-4" aria-hidden="true" /> : null}
                </button>
                <button
                  type="button"
                  onClick={() => void handleSkip()}
                  disabled={saving || skipping}
                  className="mt-btn mt-btn-ghost min-h-[48px]"
                >
                  {skipping ? "正在进入…" : "暂时跳过，使用模板教学"}
                </button>
              </div>
              <p className="text-center text-xs leading-5 text-[var(--muted-foreground)]">
                跳过后仍可使用核心练习，并随时在“设置”中完成配置。
              </p>
            </form>
          )}
        </section>
      </div>
    </main>
  );
}

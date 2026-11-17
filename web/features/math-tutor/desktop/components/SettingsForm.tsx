'use client'

import { productClass } from '@/styles/product-classes'

import { useI18n } from '@/lib/i18n'
import {
  CheckCircle2,
  ChevronDown,
  KeyRound,
  Loader2,
  PlugZap,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import type { DesktopSettings, ProviderPreset, TestConnectionResult } from '../types'

export interface FormMessage {
  kind: 'ok' | 'error'
  text: string
}

export interface SettingsFormData {
  visionMode?: 'auto' | 'enabled' | 'disabled'
  presets: ProviderPreset[]
  settings: DesktopSettings | null
  presetId: string
  apiKey: string
  baseUrl: string
  model: string
  keyMasked: string | null
  advancedOpen: boolean
  models: string[] | null
  saving: boolean
  testing: boolean
  discovering: boolean
  removing: boolean
  confirmingRemoval: boolean
  testResult: TestConnectionResult | null
  message: FormMessage | null
}

export interface SettingsFormHandlers {
  onVisionModeChange?: (mode: 'auto' | 'enabled' | 'disabled') => void
  onPresetChange: (presetId: string) => void
  onApiKeyChange: (value: string) => void
  onBaseUrlChange: (value: string) => void
  onModelChange: (value: string) => void
  onToggleAdvanced: () => void
  onDiscoverModels: () => void
  onSave: (e: React.FormEvent) => void
  onTest: () => void
  onAskRemove: () => void
  onCancelRemove: () => void
  onRemove: () => void
}

/**
 * Presentational settings form. The API key is held in React state only and
 * sent via PUT /settings; the masked tail returned by the backend is the only
 * key material ever shown. No browser storage is touched.
 */
export function SettingsForm({
  data,
  handlers,
}: {
  data: SettingsFormData
  handlers: SettingsFormHandlers
}) {
  const { t } = useI18n()
  const currentPreset = data.presets.find(p => p.preset_id === data.presetId) ?? null
  const providerSaved = data.settings?.preset_id === data.presetId
  const formSaved =
    providerSaved &&
    !data.apiKey.trim() &&
    data.model === (data.settings?.model ?? '') &&
    data.baseUrl === (data.settings?.base_url ?? '') &&
    (data.visionMode ?? 'auto') === (data.settings?.vision_mode ?? 'auto')
  const canTest =
    formSaved &&
    (data.visionMode ?? 'auto') === (data.settings?.vision_mode ?? 'auto') &&
    (currentPreset?.local ? Boolean(data.baseUrl.trim()) : Boolean(data.settings?.is_configured))
  const connectionLabel = !formSaved
    ? '未保存'
    : data.testing
      ? '正在连接'
      : data.settings?.connection_status === 'success'
        ? '连接成功'
        : data.settings?.connection_status === 'failure'
          ? '连接失败'
          : data.settings?.is_configured
            ? '已配置'
            : '未配置'

  return (
    <form
      onSubmit={handlers.onSave}
      className={productClass('mt-card flex flex-col gap-5 p-5')}
      aria-label={t('AI 模型设置')}
    >
      <div className={productClass('flex items-center justify-between gap-3')}>
        <div>
          <h3 className="text-lg font-bold tracking-tight">{t('生成模型')}</h3>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {t('用于 Tutor 表达与练习候选生成；数学验证仍由确定性后端完成。')}
          </p>
        </div>
        <span
          className={productClass(
            `shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${connectionLabel === '连接成功' ? 'bg-emerald-100 text-[var(--success)]' : connectionLabel === '连接失败' ? 'bg-rose-100 text-rose-700' : 'bg-[var(--muted)] text-[var(--muted-foreground)]'}`
          )}
        >
          {t(connectionLabel)}
        </span>
      </div>
      {/* Provider */}
      <div className={productClass('flex flex-col gap-2')}>
        <span className="text-sm font-medium text-[var(--foreground)]">{t('模型服务商')}</span>
        <div
          className={productClass('flex flex-wrap gap-2')}
          role="radiogroup"
          aria-label={t('模型服务商')}
        >
          {data.presets.map(preset => {
            const selected = preset.preset_id === data.presetId
            return (
              <button
                key={preset.preset_id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => handlers.onPresetChange(preset.preset_id)}
                className={productClass(
                  `inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] ${
                    selected
                      ? 'border-[var(--primary)] bg-[var(--primary-soft)] text-[var(--primary-text)]'
                      : 'border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--ring)]'
                  }`
                )}
              >
                <span className={productClass('flex flex-col items-start')}>
                  <span>
                    {preset.preset_id === 'custom' ? t('自定义 (OpenAI 兼容)') : preset.label}
                  </span>
                  {preset.local ? (
                    <span className="text-[10px] font-normal opacity-60">{t('本地运行')}</span>
                  ) : null}
                </span>
                {preset.custom && <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />}
              </button>
            )
          })}
        </div>
      </div>

      {/* API key — password input, never echoes the full key */}
      {currentPreset?.requires_api_key !== false ? (
        <div className={productClass('flex flex-col gap-2')}>
          <label htmlFor="settings-apikey" className="text-sm font-medium text-[var(--foreground)]">
            {t('API 密钥')}
          </label>
          <div className={productClass('flex flex-col gap-1.5')}>
            <div className="relative">
              <KeyRound
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]"
                aria-hidden="true"
              />
              <input
                id="settings-apikey"
                type="password"
                autoComplete="off"
                placeholder={
                  data.keyMasked
                    ? t('已保存：{keyMasked}（留空则保持不变）', { keyMasked: data.keyMasked })
                    : t('粘贴 API 密钥')
                }
                value={data.apiKey}
                onChange={e => handlers.onApiKeyChange(e.target.value)}
                className={productClass('mt-input h-11 pl-10 pr-3')}
              />
            </div>
            <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
              {data.keyMasked
                ? t(
                    '当前密钥尾号 {keyMasked}。密钥保存在系统安全凭据存储中，不会在界面或浏览器存储中回显。',
                    { keyMasked: data.keyMasked }
                  )
                : t('密钥仅保存在系统安全凭据存储中，不会保存在浏览器存储里。')}
            </p>
            {providerSaved && data.keyMasked ? (
              data.confirmingRemoval ? (
                <div
                  className={productClass(
                    'mt-note mt-note-danger flex flex-wrap items-center gap-2 p-3 text-sm'
                  )}
                >
                  <span className="mr-auto">
                    {t('移除后将立即回到模板教学，学习数据不会被删除。')}
                  </span>
                  <button
                    type="button"
                    onClick={handlers.onCancelRemove}
                    disabled={data.saving || data.testing || data.removing || data.discovering}
                    className="min-h-[40px] rounded-lg px-3 font-medium hover:bg-[var(--accent)]"
                  >
                    {t('取消')}
                  </button>
                  <button
                    type="button"
                    onClick={handlers.onRemove}
                    disabled={data.saving || data.testing || data.removing || data.discovering}
                    className={productClass('mt-btn mt-btn-danger-solid')}
                  >
                    {data.removing ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : null}
                    {t('确认移除')}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={handlers.onAskRemove}
                  className="min-h-[40px] w-fit text-sm font-medium text-[var(--destructive)] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                >
                  {t('移除已保存的 API Key')}
                </button>
              )
            ) : null}
          </div>
        </div>
      ) : (
        <div className="mt-note mt-note-success px-3 py-2 text-sm">
          {t('Ollama 在本机运行，不需要 API Key。')}
        </div>
      )}

      {/* Custom / advanced foldout */}
      <div className={productClass('flex flex-col gap-2')}>
        <button
          type="button"
          onClick={handlers.onToggleAdvanced}
          aria-expanded={data.advancedOpen}
          className="inline-flex min-h-[40px] w-fit cursor-pointer items-center gap-1.5 text-sm font-medium text-[var(--primary-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
        >
          {currentPreset?.custom ? t('自定义模型') : t('高级选项')}
          <ChevronDown
            className={productClass(
              `h-4 w-4 transition-transform duration-200 ${data.advancedOpen ? 'rotate-180' : ''}`
            )}
            aria-hidden="true"
          />
        </button>
        {data.advancedOpen && (
          <div
            className={productClass(
              'flex flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4'
            )}
          >
            <div className={productClass('flex flex-col gap-2')}>
              <label
                htmlFor="settings-baseurl"
                className="text-sm font-medium text-[var(--foreground)]"
              >
                {t('服务地址（Base URL）')}
              </label>
              <input
                id="settings-baseurl"
                type="text"
                autoComplete="off"
                placeholder={
                  currentPreset?.local
                    ? 'http://127.0.0.1:11434'
                    : currentPreset?.custom
                      ? t('https://…（必填）')
                      : t('使用服务商默认地址')
                }
                value={data.baseUrl}
                onChange={e => handlers.onBaseUrlChange(e.target.value)}
                readOnly={!currentPreset?.editable_base_url}
                className={productClass('mt-input h-11')}
              />
              <p className="text-xs text-[var(--muted-foreground)]">
                {t('默认使用服务商地址，可修改。API Key 将发送到此地址，请仅填写可信服务。')}
              </p>
              {currentPreset?.base_url && (
                <button
                  type="button"
                  onClick={() => handlers.onBaseUrlChange(currentPreset.base_url!)}
                  className="w-fit text-xs text-[var(--primary-text)]"
                >
                  {t('恢复默认地址')}
                </button>
              )}
            </div>
            <div className={productClass('flex flex-col gap-2')}>
              <label
                htmlFor="settings-model"
                className="text-sm font-medium text-[var(--foreground)]"
              >
                {t('模型名称')}
              </label>
              <input
                id="settings-model"
                type="text"
                autoComplete="off"
                placeholder={
                  currentPreset?.custom ? t('例如 deepseek-chat（必填）') : t('使用服务商默认模型')
                }
                value={data.model}
                onChange={e => handlers.onModelChange(e.target.value)}
                className={productClass('mt-input h-11')}
              />
            </div>
            {(currentPreset?.custom || currentPreset?.local) && (
              <button
                type="button"
                onClick={handlers.onDiscoverModels}
                disabled={data.discovering || !providerSaved}
                className={productClass('mt-btn mt-btn-primary w-fit')}
              >
                {data.discovering ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCw className="h-4 w-4" aria-hidden="true" />
                )}
                {currentPreset?.local ? t('读取本机模型') : t('发现可用模型')}
              </button>
            )}
            <label className={productClass('flex flex-col gap-2 text-sm font-medium')}>
              {t('图片输入能力')}
              <select
                value={data.visionMode ?? 'auto'}
                onChange={event =>
                  handlers.onVisionModeChange?.(
                    event.target.value as 'auto' | 'enabled' | 'disabled'
                  )
                }
                className="h-11 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3"
              >
                <option value="auto">{t('自动识别（默认）')}</option>
                <option value="enabled">{t('启用（已确认模型支持视觉）')}</option>
                <option value="disabled">{t('关闭（纯文本模型）')}</option>
              </select>
              <span className="text-xs font-normal text-[var(--muted-foreground)]">
                {t(
                  '未识别的视觉模型或自定义别名可选择启用。仅适用于兼容图片输入的服务；此选项不会让纯文本模型获得视觉能力。'
                )}
              </span>
            </label>
            {(currentPreset?.custom || currentPreset?.local) && !providerSaved ? (
              <p className="text-xs text-[var(--muted-foreground)]">
                {t('先保存当前服务商，再读取可用模型。')}
              </p>
            ) : null}
            {data.models !== null && data.models.length > 0 && (
              <ul className={productClass('flex flex-wrap gap-2')} aria-label={t('发现到的模型')}>
                {data.models.map(m => (
                  <li key={m}>
                    <button
                      type="button"
                      onClick={() => handlers.onModelChange(m)}
                      className={productClass(
                        `rounded-full border px-3 py-1.5 text-xs ${data.model === m ? 'border-[var(--primary)] bg-[var(--primary-soft)] text-[var(--primary-text)]' : 'border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]'}`
                      )}
                    >
                      {m}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className={productClass('flex flex-col gap-3 border-t border-[var(--border)] pt-4')}>
        {data.message && (
          <p
            role="status"
            className={productClass(
              `flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${
                data.message.kind === 'ok'
                  ? 'bg-emerald-50 text-[var(--success)] dark:bg-emerald-950/40'
                  : 'bg-red-50 text-[var(--destructive)] dark:bg-red-950/40'
              }`
            )}
          >
            {data.message.kind === 'ok' ? (
              <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
            ) : null}
            {t(data.message.text)}
          </p>
        )}

        <div className={productClass('flex flex-wrap items-center gap-2')}>
          <button
            type="submit"
            disabled={data.saving || data.testing || data.removing || data.discovering}
            className={productClass('mt-btn mt-btn-primary')}
          >
            {data.saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {data.saving ? t('保存中…') : t('保存设置')}
          </button>
          <button
            type="button"
            onClick={handlers.onTest}
            disabled={data.saving || data.testing || data.removing || data.discovering || !canTest}
            className={productClass('mt-btn')}
          >
            {data.testing ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <PlugZap className="h-4 w-4" aria-hidden="true" />
            )}
            {t('测试连接')}
          </button>
        </div>
      </div>
    </form>
  )
}

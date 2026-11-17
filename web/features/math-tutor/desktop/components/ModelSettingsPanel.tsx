'use client'

import { useI18n } from '@/lib/i18n'
import { Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  DesktopApiError,
  fetchModels,
  fetchPresets,
  fetchSettings,
  removeApiKey,
  saveSettings,
  testModelConnection,
} from '../lib/desktop-api'
import { SettingsOperations } from '../lib/settings-operations'
import type { DesktopSettings, ModelTestResult, ProviderPreset } from '../types'
import EmbeddingSettingsPanel from './EmbeddingSettingsPanel'
import { useToast } from './ToastProvider'
import { SettingsForm, type FormMessage } from './SettingsForm'
import { ModelTestCard } from './ModelTestCard'

export interface ModelSettingsPanelProps {
  /** Injectable fetchers — defaults hit the desktop bridge (tests pass fakes). */
  fetchSettingsFn?: typeof fetchSettings
  fetchPresetsFn?: typeof fetchPresets
  saveSettingsFn?: typeof saveSettings
  testModelConnectionFn?: typeof testModelConnection
  fetchModelsFn?: typeof fetchModels
  removeApiKeyFn?: typeof removeApiKey
}

/**
 * 设置 → AI 模型。The API key lives in React state only while this panel is
 * mounted, is sent exclusively via PUT /settings, and is never echoed back —
 * the UI shows the masked tail returned by the backend. Nothing here touches
 * localStorage/sessionStorage/IndexedDB.
 */
export default function ModelSettingsPanel({
  fetchSettingsFn = fetchSettings,
  fetchPresetsFn = fetchPresets,
  saveSettingsFn = saveSettings,
  testModelConnectionFn = testModelConnection,
  fetchModelsFn = fetchModels,
  removeApiKeyFn = removeApiKey,
}: ModelSettingsPanelProps) {
  const { t } = useI18n()
  const operations = useRef(new SettingsOperations())
  const editConfiguration = () => {
    operations.current.edit()
    setModelTest(null)
  }
  const [presets, setPresets] = useState<ProviderPreset[]>([])
  const [settings, setSettings] = useState<DesktopSettings | null>(null)
  const [presetId, setPresetId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [visionMode, setVisionMode] = useState<'auto' | 'enabled' | 'disabled'>('auto')
  const [model, setModel] = useState('')
  const [keyMasked, setKeyMasked] = useState<string | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [models, setModels] = useState<string[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [confirmingRemoval, setConfirmingRemoval] = useState(false)
  const [modelTest, setModelTest] = useState<ModelTestResult | null>(null)
  const [message, setMessage] = useState<FormMessage | null>(null)
  const toast = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, s] = await Promise.all([fetchPresetsFn(), fetchSettingsFn()])
      if (s.accepted === false) throw new Error('模型配置已变化，请重新读取后再保存。')
      setPresets(p)
      setSettings(s)
      setVisionMode(s.vision_mode ?? 'auto')
      setPresetId(s.preset_id)
      setBaseUrl(s.base_url || p.find(preset => preset.preset_id === s.preset_id)?.base_url || '')
      setModel(s.model)
      setKeyMasked(s.key_masked)
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '读取设置失败，请稍后再试。',
      })
    } finally {
      setLoading(false)
    }
  }, [fetchPresetsFn, fetchSettingsFn])

  useEffect(() => {
    load().catch(() => undefined)
  }, [load])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    const currentPreset = presets.find(p => p.preset_id === presetId) ?? null
    if (!currentPreset) return
    const operation = operations.current.begin('save', {
      preset_id: currentPreset.preset_id,
      revision: settings?.revision,
      epoch: settings?.epoch,
    })
    if (!operation) return
    setSaving(true)
    setMessage(null)
    try {
      const result = await saveSettingsFn({
        expected_revision: operation.revision,
        expected_epoch: operation.epoch,
        operation_id: operation.id,
        preset_id: currentPreset.preset_id,
        vision_mode: visionMode,
        api_key: apiKey.trim() || undefined,
        base_url: currentPreset.editable_base_url ? baseUrl.trim() : undefined,
        model: model.trim() || undefined,
      })
      if (
        !operations.current.accepts(operation, result, true) ||
        result.preset_id !== operation.preset_id
      ) {
        setMessage({
          kind: 'error',
          text: '配置已变化，本次保存回执未应用。请重新读取已生效配置。',
        })
        return
      }
      if (operations.current.unchanged(operation)) {
        setKeyMasked(result.key_masked)
        setApiKey('')
        setBaseUrl(result.base_url)
        setModel(result.model)
        setVisionMode(result.vision_mode ?? 'auto')
      }
      setSettings(current =>
        current
          ? {
              ...current,
              revision: result.revision,
              current_revision: result.current_revision,
              epoch: result.epoch,
              accepted: result.accepted,
              persisted: result.persisted,
              persistence_error: result.persistence_error,
              connection_status: result.connection_status,
              preset_id: result.preset_id,
              vision_mode: result.vision_mode ?? 'auto',
              base_url: result.base_url,
              model: result.model,
              is_configured: result.is_configured,
              onboarding_completed: result.onboarding_completed,
              key_masked: result.key_masked,
              provider_configs: {
                ...(current.provider_configs ?? {}),
                [result.preset_id]: {
                  vision_mode: result.vision_mode ?? 'auto',
                  model: result.model,
                  base_url: result.base_url,
                  has_api_key: Boolean(result.key_masked),
                  key_masked: result.key_masked,
                },
              },
            }
          : current
      )
      const saved = result.persisted === true
      const text = !saved
        ? '本次运行已生效，尚未保存到磁盘。请重试保存；重启后可能恢复上次配置。'
        : !operations.current.unchanged(operation)
          ? '上次提交已保存，当前仍有未保存修改。'
          : currentPreset.local
            ? 'Ollama 设置已保存。'
            : currentPreset.custom
              ? '自定义模型已保存并生效。'
              : '模型设置已保存并生效。'
      setMessage({ kind: saved ? 'ok' : 'error', text })
      toast({
        title: t(saved ? '模型设置已保存' : '配置尚未保存到磁盘'),
        description: t(text),
        tone: saved ? 'success' : 'error',
      })
      if (saved && operations.current.unchanged(operation) && result.initial_assessment_required)
        window.location.assign('/onboarding/assessment')
    } catch (err) {
      setMessage({
        kind: 'error',
        text:
          err instanceof DesktopApiError
            ? err.message
            : '保存结果尚未确认，输入已保留。请重新读取配置后再决定是否保存。',
      })
    } finally {
      operations.current.finish(operation)
      setSaving(false)
    }
  }

  const handleTest = async () => {
    const operation = operations.current.begin('test', {
      preset_id: presetId,
      revision: settings?.revision,
      epoch: settings?.epoch,
    })
    if (!operation) return
    setTesting(true)
    setModelTest(null)
    try {
      const result = await testModelConnectionFn({
        revision: operation.revision,
        epoch: operation.epoch,
        operation_id: operation.id,
      })
      if (
        !operations.current.accepts(operation, result) ||
        !operations.current.unchanged(operation)
      ) {
        setMessage({ kind: 'error', text: '配置已变化，本次测试结果未应用。请测试当前配置。' })
        return
      }
      setModelTest(result)
      if (result.ok && result.resolved_model) setModel(result.resolved_model)
      setSettings(current =>
        current
          ? {
              ...current,
              persisted: result.persisted,
              persistence_error: result.persistence_error,
              connection_status: result.ok ? 'success' : 'failure',
              is_configured: result.ok ? true : current.is_configured,
              model: result.ok && result.resolved_model ? result.resolved_model : current.model,
              provider_configs:
                result.ok && result.resolved_model
                  ? {
                      ...(current.provider_configs ?? {}),
                      [current.preset_id]: {
                        ...(current.provider_configs?.[current.preset_id] ?? {}),
                        model: result.resolved_model,
                        base_url: current.base_url,
                        has_api_key: Boolean(current.key_masked),
                        key_masked: current.key_masked,
                      },
                    }
                  : current.provider_configs,
            }
          : current
      )
      toast({
        title: t(result.ok ? '模型连接成功' : '模型连接失败'),
        description: t(
          result.message || (result.ok ? '配置可以使用。' : '请检查密钥、网络和模型名称。')
        ),
        tone: result.ok ? 'success' : 'error',
      })
    } catch (err) {
      if (!operations.current.unchanged(operation)) return
      setModelTest({
        ok: false,
        error_kind: null,
        message: err instanceof DesktopApiError ? err.message : '连接测试失败。',
      })
    } finally {
      operations.current.finish(operation)
      setTesting(false)
    }
  }

  const handleDiscover = async () => {
    const operation = operations.current.begin('discover', {
      preset_id: presetId,
      revision: settings?.revision,
      epoch: settings?.epoch,
    })
    if (!operation) return
    setDiscovering(true)
    try {
      const discovered = await fetchModelsFn()
      if (operations.current.unchanged(operation)) setModels(discovered)
    } catch (err) {
      if (!operations.current.unchanged(operation)) return
      setModels(null)
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '模型发现失败，请稍后再试。',
      })
    } finally {
      operations.current.finish(operation)
      setDiscovering(false)
    }
  }

  const handleRemove = async () => {
    const operation = operations.current.begin('remove', {
      preset_id: settings?.preset_id || presetId,
      revision: settings?.revision,
      epoch: settings?.epoch,
    })
    if (!operation) return
    setRemoving(true)
    setMessage(null)
    try {
      const next = await removeApiKeyFn({
        revision: operation.revision,
        epoch: operation.epoch,
        operation_id: operation.id,
      })
      if (!operations.current.accepts(operation, next, true)) {
        setMessage({
          kind: 'error',
          text: '配置已变化，本次保存回执未应用。请重新读取已生效配置。',
        })
        return
      }
      setSettings(next)
      if (operations.current.unchanged(operation)) {
        setKeyMasked(null)
        setApiKey('')
      }
      setModelTest(null)
      setConfirmingRemoval(false)
      setMessage({
        kind: 'ok',
        text: next.persisted
          ? 'API Key 已移除，已切换为模板教学。'
          : 'API Key 已移除，但配置尚未保存到磁盘。请重试保存。',
      })
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '移除失败，请稍后再试。',
      })
    } finally {
      operations.current.finish(operation)
      setRemoving(false)
    }
  }

  const modelPanel = loading ? (
    <div className="flex min-h-[240px] items-center justify-center text-sm text-[var(--muted-foreground)]">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
      {t('正在加载设置…')}
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
        onPresetChange: id => {
          editConfiguration()
          const preset = presets.find(item => item.preset_id === id)
          const profile = settings?.provider_configs?.[id]
          setPresetId(id)
          setVisionMode(profile?.vision_mode ?? 'auto')
          setApiKey('')
          setBaseUrl(profile?.base_url ?? preset?.base_url ?? '')
          setModel(profile?.model ?? preset?.default_model ?? '')
          setKeyMasked(
            profile?.key_masked ??
              (id === settings?.preset_id ? (settings?.key_masked ?? null) : null)
          )
          setModels(null)
          if (preset?.local) setAdvancedOpen(true)
          setMessage(null)
          setModelTest(null)
        },
        onApiKeyChange: value => {
          editConfiguration()
          setApiKey(value)
        },
        onBaseUrlChange: value => {
          editConfiguration()
          setBaseUrl(value)
        },
        onModelChange: value => {
          editConfiguration()
          setModel(value)
          setVisionMode('auto')
        },
        onVisionModeChange: value => {
          editConfiguration()
          setVisionMode(value)
        },
        onToggleAdvanced: () => setAdvancedOpen(v => !v),
        onDiscoverModels: handleDiscover,
        onSave: handleSave,
        onTest: handleTest,
        onAskRemove: () => setConfirmingRemoval(true),
        onCancelRemove: () => setConfirmingRemoval(false),
        onRemove: handleRemove,
      }}
    />
  )
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold tracking-tight">{t('模型与 API')}</h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t('配置生成模型和可选的资料 Embedding。密钥只进入系统安全凭据存储。')}
        </p>
      </div>
      {modelPanel}
      {modelTest ? <ModelTestCard result={modelTest} /> : null}
      {settings && !settings.is_configured && (
        <p className="mt-note mt-note-warning px-3 py-2 text-sm">
          {t('尚未配置 AI 模型 —— 核心练习功能不受影响，配置后可解锁个性化辅导与推荐练习。')}
        </p>
      )}
      <EmbeddingSettingsPanel />
    </div>
  )
}

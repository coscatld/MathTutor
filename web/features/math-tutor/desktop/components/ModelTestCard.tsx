'use client'

import { useI18n } from '@/lib/i18n'
import {
  CheckCircle2,
  CircleHelp,
  KeyRound,
  RefreshCw,
  ShieldAlert,
  TriangleAlert,
  WifiOff,
  XCircle,
} from 'lucide-react'
import { modelErrorCopy } from '../lib/desktop-api'
import type { ModelErrorKind, ModelTestResult } from '../types'

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
}

/**
 * Five-kind model connection result card. Maps ``error_kind`` onto distinct
 * friendly copy and a suggested action; renders the backend's friendly
 * ``message`` as plain text. NEVER raw HTTP tracebacks / Authorization
 * headers / API keys / internal stacks.
 */
export function ModelTestCard({ result }: { result: ModelTestResult }) {
  const { t } = useI18n()
  if (result.ok) {
    return (
      <p role="status" className="mt-note mt-note-success flex flex-col gap-0.5 px-3 py-2 text-sm">
        <span className="flex items-center gap-1.5 font-medium">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          {t('连接成功，模型可正常调用')}
        </span>
        {result.message ? <span className="text-xs opacity-90">{t(result.message)}</span> : null}
      </p>
    )
  }

  const copy = modelErrorCopy(result.error_kind)
  const ErrorIcon = result.error_kind
    ? (MODEL_ERROR_ICONS[result.error_kind] ?? TriangleAlert)
    : TriangleAlert
  return (
    <div role="status" className="mt-note mt-note-danger flex flex-col gap-1 px-3 py-2 text-sm">
      <span className="flex items-center gap-1.5 font-medium">
        <ErrorIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {t(copy.title)}
      </span>
      {result.message ? <span>{t(result.message)}</span> : null}
      <span className="text-xs opacity-90">{t(copy.advice)}</span>
    </div>
  )
}

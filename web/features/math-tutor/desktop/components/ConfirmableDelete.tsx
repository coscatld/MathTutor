'use client'

import { productClass } from '@/styles/product-classes'

import { useI18n } from '@/lib/i18n'
import { Loader2, Trash2 } from 'lucide-react'

export function ConfirmableDelete({
  title,
  detail,
  confirming,
  busy,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  title: string
  detail: string
  confirming: boolean
  busy: boolean
  onAskDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
}) {
  const { t } = useI18n()
  if (confirming) {
    return (
      <div className={productClass('flex flex-wrap items-center justify-between gap-2')}>
        <span className="text-sm font-medium text-[var(--destructive)]">
          {t('确认删除「{title}」？此操作无法撤销。', { title })}
        </span>
        <span className={productClass('flex items-center gap-2')}>
          <button
            type="button"
            onClick={onCancelDelete}
            disabled={busy}
            className={productClass('mt-btn')}
          >
            {t('取消')}
          </button>
          <button
            type="button"
            onClick={onConfirmDelete}
            disabled={busy}
            className={productClass('mt-btn mt-btn-danger-solid')}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            )}
            {t('确认删除')}
          </button>
        </span>
      </div>
    )
  }
  return (
    <div className={productClass('flex flex-wrap items-center justify-between gap-2')}>
      <span className={productClass('flex min-w-0 flex-col')}>
        <span className="truncate text-sm font-medium text-[var(--foreground)]">{title}</span>
        <span className="truncate text-xs text-[var(--muted-foreground)]">{detail}</span>
      </span>
      <button
        type="button"
        onClick={onAskDelete}
        disabled={busy}
        aria-label={t('删除 {title}', { title: title })}
        className={productClass('mt-btn mt-btn-danger')}
      >
        <Trash2 className="h-4 w-4" aria-hidden="true" />
        {t('删除')}
      </button>
    </div>
  )
}

'use client'

import { productClass } from '@/styles/product-classes'

import { useI18n } from '@/lib/i18n'
import {
  BrainCircuit,
  DatabaseZap,
  Download,
  FileText,
  Loader2,
  LockKeyhole,
  ShieldCheck,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'
import { formatBytes } from '../lib/desktop-api'
import { DOCUMENT_STATUS_LABELS, MEMORY_TYPE_LABELS } from '../lib/labels'
import { usePrivacyData, type PrivacyDataOptions } from '../hooks/usePrivacyData'
import { memoryObjectText } from './MemoryRow'
import { PrivacySummary } from './PrivacySummary'
import { ConfirmableDelete } from './ConfirmableDelete'
export { PrivacySummary } from './PrivacySummary'
export { ConfirmableDelete } from './ConfirmableDelete'

interface Props extends PrivacyDataOptions {
  onClose?: () => void
  embedded?: boolean
}

/**
 * 我的数据：profile 只读展示 + 我的记忆 + 我的资料文档（逐条删除均需
 * 二次确认）+ Student Model 只读摘要 + 数据工具（重建索引 / 导出）+
 * 危险操作区（清空文档 / 清空记忆 / 删除学习记录，全部二次确认）。
 * 删除复用现有 desktop bridge 端点（与 DocumentsPanel / MemoryPanel
 * 同一套契约）。无任何 mastery 编辑入口。
 */
export default function PrivacyPanel({ onClose, embedded = false, ...dataOptions }: Props) {
  const { t } = useI18n()
  const {
    memories,
    documents,
    summary,
    loading,
    busyId,
    confirmMemoryId,
    setConfirmMemoryId,
    confirmDocId,
    setConfirmDocId,
    confirmDanger,
    setConfirmDanger,
    message,
    handleDeleteMemory,
    handleDeleteDocument,
    handleDanger,
    handleRebuildIndexes,
    handleExport,
    handleRecompute,
    purgeDocumentsFn,
    purgeMemoryFn,
    deleteHistoryFn,
  } = usePrivacyData(dataOptions)

  const gradeBand = summary?.skills.find(s => s.grade_band)?.grade_band ?? null

  return (
    <div
      className={productClass(
        embedded ? 'w-full' : 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'
      )}
      role={embedded ? undefined : 'dialog'}
      aria-modal={embedded ? undefined : true}
      aria-labelledby="privacy-title"
    >
      <div
        className={productClass(
          embedded
            ? 'flex w-full flex-col'
            : 'flex max-h-[calc(100vh-4rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl'
        )}
      >
        <header
          className={productClass(
            embedded
              ? 'flex items-start justify-between gap-2'
              : 'flex items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-3.5'
          )}
        >
          {embedded ? (
            <div>
              <h1
                id="privacy-title"
                className="text-xl font-bold tracking-tight text-[var(--foreground)]"
              >
                {t('数据与隐私')}
              </h1>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t('查看、导出或删除保存在这台电脑上的记忆、资料与学习记录。')}
              </p>
            </div>
          ) : (
            <h1
              id="privacy-title"
              className={productClass(
                'flex items-center gap-2 text-lg font-semibold text-[var(--foreground)]'
              )}
            >
              <ShieldCheck className="h-5 w-5 text-[var(--primary-text)]" aria-hidden="true" />
              {t('数据与隐私')}
            </h1>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label={t('关闭')}
              className={productClass('mt-btn mt-btn-ghost justify-center')}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </header>

        <div
          className={productClass(
            embedded
              ? 'mt-5 flex flex-col gap-6'
              : 'flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-4'
          )}
        >
          {message && (
            <p
              role="status"
              className={productClass(
                `rounded-xl px-3 py-2 text-sm ${
                  message.kind === 'ok'
                    ? 'bg-emerald-50 text-[var(--success)] dark:bg-emerald-950/40'
                    : 'bg-red-50 text-[var(--destructive)] dark:bg-red-950/40'
                }`
              )}
            >
              {t(message.text, message.params)}
            </p>
          )}

          {loading ? (
            <p
              className={productClass(
                'flex items-center gap-2 py-8 text-sm text-[var(--muted-foreground)]'
              )}
            >
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t('正在加载数据管理…')}
            </p>
          ) : (
            <>
              {/* Profile — read-only display */}
              {!embedded && (
                <section className={productClass('flex flex-col gap-2')} aria-label={t('我的资料')}>
                  <h2
                    className={productClass(
                      'flex items-center gap-2 text-base font-semibold text-[var(--foreground)]'
                    )}
                  >
                    <UserRound className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
                    {t('我的资料')}
                  </h2>
                  <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div
                      className={productClass(
                        'flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3'
                      )}
                    >
                      <dt className="text-xs text-[var(--muted-foreground)]">{t('学段')}</dt>
                      <dd className="text-sm font-medium text-[var(--foreground)]">
                        {gradeBand ? t(gradeBand) : '—'}
                      </dd>
                    </div>
                    <div
                      className={productClass(
                        'flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3'
                      )}
                    >
                      <dt className="text-xs text-[var(--muted-foreground)]">
                        {t('累计练习次数')}
                      </dt>
                      <dd className="text-sm font-medium text-[var(--foreground)]">
                        {summary?.total_attempts ?? 0}
                      </dd>
                    </div>
                    <div
                      className={productClass(
                        'flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3'
                      )}
                    >
                      <dt className="text-xs text-[var(--muted-foreground)]">
                        {t('活跃错误概念')}
                      </dt>
                      <dd className="text-sm font-medium text-[var(--foreground)]">
                        {summary?.active_misconceptions ?? 0}
                      </dd>
                    </div>
                  </dl>
                  <p
                    className={productClass(
                      'flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]'
                    )}
                  >
                    <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('以上资料由系统自动生成，只读展示。')}
                  </p>
                </section>
              )}

              {/* Memories — delete with double confirm */}
              <section className={productClass('flex flex-col gap-2')} aria-label={t('我的记忆')}>
                <h2
                  className={productClass(
                    'flex items-center gap-2 text-base font-semibold text-[var(--foreground)]'
                  )}
                >
                  <BrainCircuit className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
                  {t('我的记忆')}
                </h2>
                {memories.length === 0 ? (
                  <p className="text-sm text-[var(--muted-foreground)]">{t('还没有记忆。')}</p>
                ) : (
                  <ul className={productClass('flex flex-col gap-2')}>
                    {memories.map(memory => (
                      <li
                        key={memory.memory_id}
                        className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5"
                      >
                        <ConfirmableDelete
                          title={`${t(MEMORY_TYPE_LABELS[memory.memory_type] ?? memory.memory_type)}: ${memory.predicate}`}
                          detail={memoryObjectText(memory)}
                          confirming={confirmMemoryId === memory.memory_id}
                          busy={busyId === memory.memory_id}
                          onAskDelete={() => setConfirmMemoryId(memory.memory_id)}
                          onCancelDelete={() => setConfirmMemoryId(null)}
                          onConfirmDelete={() => handleDeleteMemory(memory)}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Documents — delete with double confirm */}
              <section
                className={productClass('flex flex-col gap-2')}
                aria-label={t('我的资料文档')}
              >
                <h2
                  className={productClass(
                    'flex items-center gap-2 text-base font-semibold text-[var(--foreground)]'
                  )}
                >
                  <FileText className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
                  {t('我的资料文档')}
                </h2>
                {documents.length === 0 ? (
                  <p className="text-sm text-[var(--muted-foreground)]">{t('还没有学习资料。')}</p>
                ) : (
                  <ul className={productClass('flex flex-col gap-2')}>
                    {documents.map(doc => (
                      <li
                        key={doc.document_id}
                        className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5"
                      >
                        <ConfirmableDelete
                          title={doc.filename}
                          detail={`${t(DOCUMENT_STATUS_LABELS[doc.status] ?? doc.status)} · ${formatBytes(doc.size_bytes)}`}
                          confirming={confirmDocId === doc.document_id}
                          busy={busyId === doc.document_id}
                          onAskDelete={() => setConfirmDocId(doc.document_id)}
                          onCancelDelete={() => setConfirmDocId(null)}
                          onConfirmDelete={() => handleDeleteDocument(doc)}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Student model summary — strictly read-only */}
              {!embedded && (
                <section
                  className={productClass('flex flex-col gap-2')}
                  aria-label={t('学习模型摘要')}
                >
                  <h2
                    className={productClass(
                      'flex items-center gap-2 text-base font-semibold text-[var(--foreground)]'
                    )}
                  >
                    <ShieldCheck
                      className="h-4 w-4 text-[var(--primary-text)]"
                      aria-hidden="true"
                    />
                    {t('学习模型摘要')}
                  </h2>
                  {summary ? <PrivacySummary summary={summary} /> : null}
                </section>
              )}

              {/* Data tools — non-destructive */}
              <section className={productClass('flex flex-col gap-2')} aria-label={t('数据工具')}>
                <h2
                  className={productClass(
                    'flex items-center gap-2 text-base font-semibold text-[var(--foreground)]'
                  )}
                >
                  <DatabaseZap className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
                  {t('数据工具')}
                </h2>
                <div className={productClass('flex flex-wrap gap-2')}>
                  <button
                    type="button"
                    onClick={handleRebuildIndexes}
                    disabled={busyId !== null}
                    className={productClass('mt-btn')}
                  >
                    {busyId === 'rebuild-indexes' ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <DatabaseZap className="h-4 w-4" aria-hidden="true" />
                    )}
                    {t('重建检索索引')}
                  </button>
                  <button
                    type="button"
                    onClick={handleExport}
                    disabled={busyId !== null}
                    className={productClass('mt-btn')}
                  >
                    {busyId === 'export' ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Download className="h-4 w-4" aria-hidden="true" />
                    )}
                    {t('导出我的数据')}
                  </button>
                </div>
                <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                  {t('导出内容只包含你自己的资料、记忆与学习摘要，不含任何密钥或系统内部数据。')}
                </p>
              </section>

              <section
                aria-label={t('学习画像重算')}
                className="rounded-xl border border-[var(--border)] p-4"
              >
                <h2 className="font-medium">{t('重新计算学习画像')}</h2>
                <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
                  {t('根据有效学习事件重新计算画像与个人状态。检索索引重建只影响资料搜索。')}
                </p>
                <button
                  type="button"
                  disabled={busyId !== null}
                  className="mt-3 min-h-11 rounded-lg border border-[var(--border)] px-4 text-sm disabled:opacity-50"
                  onClick={handleRecompute}
                >
                  {busyId === 'recompute' ? t('正在计算…') : t('重新计算学习画像')}
                </button>
              </section>

              {/* Danger zone — every action confirms twice before sending */}
              <section className={productClass('flex flex-col gap-2')} aria-label={t('危险操作')}>
                <h2
                  className={productClass(
                    'flex items-center gap-2 text-base font-semibold text-[var(--destructive)]'
                  )}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  {t('危险操作')}
                </h2>
                <div
                  className={productClass(
                    'flex flex-col gap-2 rounded-xl border border-red-200 bg-red-50/60 p-3 dark:border-red-950 dark:bg-red-950/20'
                  )}
                >
                  <ConfirmableDelete
                    title={t('清空全部资料文档')}
                    detail={t('删除你导入的所有学习资料及其内容，无法撤销。')}
                    confirming={confirmDanger === 'purge-documents'}
                    busy={busyId === 'purge-documents'}
                    onAskDelete={() => setConfirmDanger('purge-documents')}
                    onCancelDelete={() => setConfirmDanger(null)}
                    onConfirmDelete={() =>
                      handleDanger(
                        'purge-documents',
                        async () => {
                          await purgeDocumentsFn()
                        },
                        '已清空全部资料文档。'
                      )
                    }
                  />
                  <ConfirmableDelete
                    title={t('清空全部记忆')}
                    detail={t('删除你的全部个人记忆，无法撤销。')}
                    confirming={confirmDanger === 'purge-memory'}
                    busy={busyId === 'purge-memory'}
                    onAskDelete={() => setConfirmDanger('purge-memory')}
                    onCancelDelete={() => setConfirmDanger(null)}
                    onConfirmDelete={() =>
                      handleDanger(
                        'purge-memory',
                        async () => {
                          await purgeMemoryFn()
                        },
                        '已清空全部记忆。'
                      )
                    }
                  />
                  <ConfirmableDelete
                    title={t('删除学习记录')}
                    detail={t(
                      '将删除学习证据及其生成的画像和个性化状态。会话内容保留，但不会自动恢复已删除的画像。备份中的旧记录需要单独管理。'
                    )}
                    confirming={confirmDanger === 'educational-history'}
                    busy={busyId === 'educational-history'}
                    onAskDelete={() => setConfirmDanger('educational-history')}
                    onCancelDelete={() => setConfirmDanger(null)}
                    onConfirmDelete={() =>
                      handleDanger(
                        'educational-history',
                        async () => {
                          await deleteHistoryFn()
                        },
                        '已删除学习记录及其生成的画像。'
                      )
                    }
                  />
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

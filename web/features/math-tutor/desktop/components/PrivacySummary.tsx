'use client'

import { useI18n } from '@/lib/i18n'
import type { StudentSummary } from '../types'
import { evidenceStatusLabel, projectEvidenceSummary } from '../../lib/teaching-contract'

export function PrivacySummary({ summary }: { summary: StudentSummary }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col gap-3" aria-label={t('学习模型摘要')}>
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        {t(
          '根据已经验证的作答记录生成。独立、受助和看答案后的作答分别记录，不把帮助次数当作掌握增长。'
        )}
      </p>
      <dl className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">{t('累计练习次数')}</dt>
          <dd className="text-sm font-medium text-[var(--foreground)]">{summary.total_attempts}</dd>
        </div>
        <div className="flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">{t('活跃错误概念')}</dt>
          <dd className="text-sm font-medium text-[var(--foreground)]">
            {summary.active_misconceptions}
          </dd>
        </div>
      </dl>
      {summary.skills.length === 0 ? (
        <p className="text-sm text-[var(--muted-foreground)]">
          {t('还没有练习记录，暂无知识点证据。')}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {summary.skills.map(skill => {
            const evidence = projectEvidenceSummary(skill.evidence_summary)
            return (
              <li
                key={skill.code}
                className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2"
              >
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm font-medium text-[var(--foreground)]">
                    {skill.label}
                  </span>
                  {skill.grade_band ? (
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {t('学段：')}
                      {t(skill.grade_band)}
                    </span>
                  ) : null}
                </span>
                <span className="flex flex-col items-end gap-1 text-xs leading-5 text-[var(--muted-foreground)]">
                  <span>
                    {evidence
                      ? t(evidenceStatusLabel(skill.evidence_status || evidence.status))
                      : t('仍需独立检测')}
                  </span>
                  {evidence ? (
                    <>
                      <span>
                        {t('独立 {independent} 次 · 受助 {assisted} 次', {
                          independent: evidence.independent,
                          assisted: evidence.assisted,
                        })}
                      </span>
                      <span>
                        {t('看答案后 {postSolution} 次 · 暂无法判断 {ungradable} 次', {
                          postSolution: evidence.post_solution,
                          ungradable: evidence.ungradable,
                        })}
                      </span>
                    </>
                  ) : (
                    <span>{t('旧记录不足以区分作答前的帮助')}</span>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/**
 * Per-item delete with inline double confirmation: the first click asks,
 * the second click (确认删除) actually deletes. The destructive request is
 * only ever sent from the confirm state.
 */

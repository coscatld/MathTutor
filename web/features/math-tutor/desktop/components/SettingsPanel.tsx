'use client'

import { productClass } from '@/styles/product-classes'

import { useI18n } from '@/lib/i18n'
import { Settings2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import ConversationTrashPanel from './ConversationTrashPanel'
import BackupPanel from './BackupPanel'
import DataPrivacySettings from './DataPrivacySettings'
import TutorPersonalityPanel from './TutorPersonalityPanel'
import CostSettingsPanel from './CostSettingsPanel'
import LearnerStagePanel from './LearnerStagePanel'
import EncryptionPanel from './EncryptionPanel'
import { useSearchParams } from 'next/navigation'
import AppearancePicker from '@/components/common/AppearancePicker'
import LanguagePicker from '@/components/common/LanguagePicker'
import ModelSettingsPanel, { type ModelSettingsPanelProps } from './ModelSettingsPanel'
import ZhihuConnection from '../../exploration/ZhihuConnection'
import { requestTutorNavigation } from '../../lib/navigation-guard'
export { SettingsForm } from './SettingsForm'
export type { FormMessage, SettingsFormData, SettingsFormHandlers } from './SettingsForm'
export { ModelTestCard } from './ModelTestCard'

const SETTINGS_SECTIONS = [
  'general',
  'model',
  'sources',
  'tutor',
  'stage',
  'data',
  'appearance',
  'advanced',
  'trash',
] as const
type SettingsSection = (typeof SETTINGS_SECTIONS)[number]
const isSettingsSection = (value: string | null | undefined): value is SettingsSection =>
  SETTINGS_SECTIONS.includes(value as SettingsSection)

export default function SettingsPanel(props: ModelSettingsPanelProps) {
  const { t } = useI18n()
  const requested = useSearchParams()?.get('section')
  const [section, setSection] = useState<SettingsSection>(
    isSettingsSection(requested) ? requested : 'model'
  )
  useEffect(() => {
    if (isSettingsSection(requested)) setSection(requested)
  }, [requested])
  const sections = [
    ['general', '通用'],
    ['model', '模型与 API'],
    ['sources', '知识来源'],
    ['tutor', 'Tutor'],
    ['stage', '学段'],
    ['data', '数据与隐私'],
    ['appearance', '外观'],
    ['advanced', '高级'],
    ['trash', '垃圾桶'],
  ] as const
  return (
    <div className={productClass('mt-settings-layout')}>
      <aside className={productClass('mt-settings-nav')}>
        <h1
          className={productClass(
            'mb-5 flex items-center gap-2 px-2 text-lg font-bold tracking-tight'
          )}
        >
          <Settings2 className="h-5 w-5 text-[var(--primary-text)]" />
          {t('设置')}
        </h1>
        <nav aria-label={t('设置分类')} className="space-y-0.5">
          {sections.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-current={section === id ? 'page' : undefined}
              onClick={() => { if (section !== 'sources' || id === 'sources' || requestTutorNavigation()) setSection(id) }}
              className={productClass(
                `w-full rounded-lg px-3 py-2 text-left text-sm ${id === 'sources' ? 'min-h-11' : ''} ${section === id ? 'bg-[var(--primary-soft)] font-semibold text-[var(--primary-text)]' : 'text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]'}`
              )}
            >
              {t(label)}
            </button>
          ))}
        </nav>
      </aside>
      <div className={productClass('mt-settings-content')}>
        <div className="mx-auto max-w-4xl">
          {section === 'trash' ? <ConversationTrashPanel /> : null}
          {section === 'general' ? (
            <section>
              <h2 className="text-xl font-bold tracking-tight">{t('通用')}</h2>
              <div className="mt-4">
                <LanguagePicker />
              </div>
              <div className={productClass('mt-card mt-4 p-5')}>
                <p className="text-sm font-semibold">{t('开箱即用')}</p>
                <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
                  {t(
                    'Embedding 与 OCR 等增强能力默认关闭；未配置模型时，核心练习、模板辅导和关键词检索仍可使用。'
                  )}
                </p>
              </div>
            </section>
          ) : null}
          <div hidden={section !== 'model'}>
            <ModelSettingsPanel {...props} />
          </div>
          {section === 'sources' ? <ZhihuConnection /> : null}
          {section === 'tutor' ? (
            <div className="space-y-8">
              <TutorPersonalityPanel />
              <CostSettingsPanel />
            </div>
          ) : null}
          {section === 'stage' ? <LearnerStagePanel /> : null}
          {section === 'data' ? <DataPrivacySettings /> : null}
          {section === 'appearance' ? (
            <section>
              <h2 className="text-xl font-bold tracking-tight">{t('外观')}</h2>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t('选择页面风格，立即生效。偏好只保存在本机。')}
              </p>
              <div className="mt-5">
                <AppearancePicker />
              </div>
            </section>
          ) : null}
          {section === 'advanced' ? (
            <div className={productClass('space-y-4')}>
              <div>
                <h2 className="text-xl font-bold tracking-tight">{t('高级')}</h2>
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                  {t('备份、恢复、加密与维护操作。')}
                </p>
              </div>
              <EncryptionPanel />
              <BackupPanel />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

import type { Metadata } from 'next';
import { ArchitectureDiagram } from '@/components/architecture-diagram';
import { t } from '@/lib/messages';
import { absUrl, isLocale, type Locale } from '@/lib/site';

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }): Promise<Metadata> {
  const { lang } = await params;
  const locale: Locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).architecturePage;
  return {
    title: copy.title,
    description: copy.intro,
    alternates: { canonical: absUrl(`/${locale}/architecture/`) },
  };
}

export default async function ArchitecturePage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).architecturePage;
  const roles =
    locale === 'zh'
      ? [
          ['LLM', '语言表达、讲解措辞、资料综合。不拥有核验权威。'],
          ['Verifier', '对支持范围内的题目与算式做确定性核验。'],
          ['State Machine', '教学回合状态、提示等级与答案披露许可。'],
          ['EvidenceTracker', '产品策略名 evidence_tracker_v2：从可信作答生成画像，而不是把自我报告写成掌握。'],
          ['DKT', '独立学生预测管道。当前最多调节一档，学习效果未在 MathTutor 真实学生数据上验证。'],
        ]
      : [
          ['LLM', 'Language and explanation. It does not own verification authority.'],
          ['Verifier', 'Deterministic checks for in-scope problems and expressions.'],
          ['State Machine', 'Turn state, hint level, and answer-disclosure permission.'],
          ['EvidenceTracker', 'Product policy evidence_tracker_v2: profiles from trusted attempts, not self-reports.'],
          ['DKT', 'A separate student-prediction pipeline. It may shift one notch. Learning effect on MathTutor students is unverified.'],
        ];

  return (
    <div className="mt-container py-16">
      <h1 className="text-4xl font-semibold tracking-tight">{copy.title}</h1>
      <p className="mt-4 max-w-3xl text-lg leading-8 text-[var(--mt-muted)]">{copy.intro}</p>
      <div className="mt-10 overflow-x-auto">
        <ArchitectureDiagram locale={locale} />
      </div>
      <dl className="mt-10 grid gap-4 md:grid-cols-2">
        {roles.map(([name, body]) => (
          <div key={name} className="rounded-2xl border border-[var(--mt-border)] bg-[var(--mt-card)] p-5">
            <dt className="font-semibold">{name}</dt>
            <dd className="mt-2 text-sm leading-7 text-[var(--mt-muted)]">{body}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-8 max-w-3xl text-sm leading-7 text-[var(--mt-muted)]">
        {locale === 'zh'
          ? '运行拓扑：Electron 壳启动 Next.js 工作台与 FastAPI 产品服务；密钥在系统凭据库，可变数据在用户数据目录。本页不暗示全部模块已经完成真实教学效果验证。'
          : 'Runtime: the Electron shell starts the Next.js workbench and FastAPI product service. Secrets stay in the OS store; mutable data stays under userData. This page does not claim classroom outcome validation for every module.'}
      </p>
    </div>
  );
}

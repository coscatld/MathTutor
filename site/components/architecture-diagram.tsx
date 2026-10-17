import type { Locale } from '@/lib/site';

const nodesZh = [
  '学生界面 Student UI',
  'Controller / 教学状态',
  'Math Solver & Verifier',
  'Learning Evidence',
  'Student Model',
  'Practice Recommendation',
  '下一轮学习循环',
];

const nodesEn = [
  'Student UI',
  'Controller / Teaching State',
  'Math Solver & Verifier',
  'Learning Evidence',
  'Student Model',
  'Practice Recommendation',
  'Next learning cycle',
];

export function ArchitectureDiagram({ locale }: { locale: Locale }) {
  const nodes = locale === 'zh' ? nodesZh : nodesEn;
  return (
    <ol className="grid gap-3 md:grid-cols-7">
      {nodes.map((label, index) => (
        <li
          key={label}
          className="relative rounded-2xl border border-[var(--mt-border)] bg-[var(--mt-card)] p-4 text-sm leading-6 min-h-[88px]"
        >
          <span className="block text-[11px] font-medium tracking-wide text-[var(--mt-blue)]">
            {String(index + 1).padStart(2, '0')}
          </span>
          {label}
        </li>
      ))}
    </ol>
  );
}

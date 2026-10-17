import { statusLabel, type FeatureStatus } from '@/lib/features';
import type { Locale } from '@/lib/site';

const tones: Record<FeatureStatus, string> = {
  implemented: 'bg-emerald-500/15 text-emerald-800 dark:text-emerald-300',
  partial: 'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  experimental: 'bg-sky-500/15 text-sky-800 dark:text-sky-300',
  planned: 'bg-zinc-500/15 text-zinc-700 dark:text-zinc-300',
};

export function StatusBadge({ status, locale }: { status: FeatureStatus; locale: Locale }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[status]}`}>
      {statusLabel[locale][status]}
    </span>
  );
}

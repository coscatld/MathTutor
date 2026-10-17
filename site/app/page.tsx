import Link from 'next/link';
import { BrandMark } from '@/components/brand-mark';
import { BASE_PATH } from '@/lib/site';

export default function RootPage() {
  const zh = `${BASE_PATH}/zh/`;
  return (
    <main className="mt-container flex min-h-[70vh] flex-col items-start justify-center gap-6 py-16">
      <script
        dangerouslySetInnerHTML={{
          __html: `location.replace(${JSON.stringify(zh)});`,
        }}
      />
      <p className="inline-flex items-center gap-2 text-lg font-semibold">
        <BrandMark className="size-6" />
        MathTutor
      </p>
      <h1 className="text-3xl font-semibold tracking-tight">选择语言 / Choose a language</h1>
      <p className="text-[var(--mt-muted)] max-w-xl leading-7">
        默认进入简体中文。若未自动跳转，请手动选择。
      </p>
      <div className="flex flex-wrap gap-3">
        <Link
          href="/zh/"
          className="inline-flex min-h-11 items-center rounded-full bg-[var(--mt-blue)] px-5 text-white"
        >
          简体中文
        </Link>
        <Link
          href="/en/"
          className="inline-flex min-h-11 items-center rounded-full border border-[var(--mt-border)] px-5"
        >
          English
        </Link>
      </div>
    </main>
  );
}

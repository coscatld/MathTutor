import Link from 'next/link';

export default function NotFound() {
  return (
    <main className="mt-container py-24">
      <h1 className="text-3xl font-semibold">404</h1>
      <p className="mt-3 max-w-xl text-[var(--mt-muted)] leading-7">
        没有找到这个页面。 / This page does not exist.
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link href="/zh/" className="underline">
          简体中文首页
        </Link>
        <Link href="/en/" className="underline">
          English home
        </Link>
      </div>
    </main>
  );
}

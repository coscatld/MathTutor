import { withBase } from '@/lib/site';

export function ScreenshotFrame({
  src,
  alt,
  priority = false,
}: {
  src: string;
  alt: string;
  priority?: boolean;
}) {
  return (
    <figure className="overflow-hidden rounded-2xl border border-[var(--mt-border)] bg-[var(--mt-card)] shadow-sm">
      {/* Native img: next/image unoptimized static export does not prefix basePath. */}
      <img
        src={withBase(src)}
        alt={alt}
        width={1600}
        height={1000}
        decoding="async"
        fetchPriority={priority ? 'high' : 'auto'}
        loading={priority ? 'eager' : 'lazy'}
        className="h-auto w-full"
      />
    </figure>
  );
}

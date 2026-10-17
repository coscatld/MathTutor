import Image from 'next/image';

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
      <Image
        src={src}
        alt={alt}
        width={1600}
        height={1000}
        priority={priority}
        className="h-auto w-full"
      />
    </figure>
  );
}

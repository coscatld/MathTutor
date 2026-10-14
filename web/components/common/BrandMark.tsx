/**
 * MathTutor mark: a staircase of verified steps climbing to the answer.
 * `animated` draws the steps once (used on the startup screen); the draw is
 * suppressed by prefers-reduced-motion through the global motion rules.
 */
export default function BrandMark({ className = "h-[18px] w-[18px]", animated = false, loop = false }: { className?: string; animated?: boolean; loop?: boolean }) {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className={className}>
    <path
      d="M4 19.5h5.2v-5.2h5.2V9h4.6"
      stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
      className={animated ? "mt-mark-steps" : undefined}
      data-loop={loop ? "true" : undefined}
      style={animated ? { strokeDasharray: 32, ["--len" as string]: 32 } : undefined}
    />
    <circle cx="19" cy="4.6" r="2" fill="currentColor" className={animated ? "mt-mark-goal" : undefined} data-loop={loop ? "true" : undefined} />
  </svg>;
}

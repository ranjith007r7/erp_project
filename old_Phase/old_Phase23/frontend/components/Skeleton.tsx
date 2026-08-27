/**
 * Real shimmer placeholders, not just "Loading..." text or a blank
 * zero-filled UI. Uses Tailwind's built-in `animate-pulse` (no custom
 * keyframes needed, ships with Tailwind core) rather than a spinner -
 * a pulsing shape in the rough size of the real content reduces layout
 * shift when the real data arrives, which a spinner doesn't.
 */
export function SkeletonLine({ width = "w-full" }: { width?: string }) {
  return <div className={`h-4 bg-slate-200 rounded animate-pulse ${width}`} />;
}

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-lg shadow-sm p-3 space-y-2">
      <SkeletonLine width="w-1/2" />
      <SkeletonLine width="w-1/3" />
    </div>
  );
}

export function SkeletonList({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

export function SkeletonStatTile() {
  return (
    <div className="bg-white rounded-lg shadow-sm p-4 text-center space-y-2">
      <div className="h-8 bg-slate-200 rounded animate-pulse w-12 mx-auto" />
      <div className="h-3 bg-slate-200 rounded animate-pulse w-16 mx-auto" />
    </div>
  );
}

/** Coloured status badge. `color` is the name the backend sends with every Workpage status. */
const COLORS: Record<string, string> = {
  slate: "bg-slate-100 text-slate-700 dark:bg-zinc-800 dark:text-zinc-200",
  blue: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  red: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300",
  teal: "bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300",
  green: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
};
export const STATUS_DOT: Record<string, string> = {
  slate: "bg-slate-400", blue: "bg-blue-500", amber: "bg-amber-500", red: "bg-red-500",
  indigo: "bg-indigo-500", teal: "bg-teal-500", green: "bg-green-500",
};

export function StatusPill({ label, color }: { label: string; color: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${COLORS[color] ?? COLORS.slate}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[color] ?? STATUS_DOT.slate}`} />
      {label}
    </span>
  );
}

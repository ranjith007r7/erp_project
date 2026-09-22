import Link from "next/link";
import type { LucideIcon } from "lucide-react";

/**
 * The exact icon + hover-background style Dashboard's header uses,
 * extracted into one shared component so every other page's PageHeader
 * actions slot looks genuinely the same, not just similar - a real gap
 * found through use: individual pages were hand-rolling plain
 * underlined-text links in their actions slot while Dashboard had this
 * richer style, so navigating from Dashboard into any inner page felt
 * inconsistent even after dark-mode contrast was fixed.
 */
export function NavLink({ href, icon: Icon, children }: { href: string; icon: LucideIcon; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm text-slate-600 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 hover:text-slate-800 dark:hover:text-white transition-colors"
    >
      <Icon size={16} /> {children}
    </Link>
  );
}

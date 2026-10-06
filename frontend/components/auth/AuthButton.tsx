import type { ButtonHTMLAttributes } from "react";
import { Check } from "lucide-react";

type Variant = "primary" | "secondary";

/** One set of classes for both <button> and <Link>, so the home page links match the form buttons. */
export function authButtonClasses(variant: Variant = "primary", extra = ""): string {
  const base =
    "group relative flex w-full items-center justify-center gap-2 overflow-hidden rounded-xl px-4 py-3 text-sm font-semibold " +
    "transition-all duration-200 focus-visible:outline-none focus-visible:ring-4 disabled:cursor-not-allowed disabled:opacity-60 active:scale-[0.985]";
  const look =
    variant === "primary"
      ? "bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-600/25 hover:shadow-xl hover:shadow-indigo-600/35 hover:brightness-110 focus-visible:ring-indigo-500/30"
      : "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 focus-visible:ring-slate-400/25 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800";
  return `${base} ${look} ${extra}`.trim();
}

/** A light sweep across the button on hover (decorative; hidden from assistive tech). */
export function Shimmer() {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute inset-y-0 -left-full w-1/2 -skew-x-12 bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 ease-out group-hover:translate-x-[400%] motion-reduce:hidden"
    />
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  loading?: boolean;
  loadingLabel?: string;
  success?: boolean;
  successLabel?: string;
};

export function AuthButton({
  variant = "primary",
  loading = false,
  loadingLabel,
  success = false,
  successLabel = "Done",
  disabled,
  className = "",
  children,
  ...rest
}: Props) {
  const successLook = success ? "!from-emerald-600 !to-emerald-600 !shadow-emerald-600/30" : "";
  return (
    <button
      disabled={disabled || loading || success}
      aria-busy={loading || undefined}
      className={authButtonClasses(variant, `${successLook} ${className}`)}
      {...rest}
    >
      {variant === "primary" && <Shimmer />}
      <span className="relative flex items-center justify-center gap-2">
        {loading && <Spinner />}
        {success && <Check size={16} aria-hidden />}
        {success ? successLabel : loading && loadingLabel ? loadingLabel : children}
      </span>
    </button>
  );
}

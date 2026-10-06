"use client";

import { useId, useState, type ElementType, type InputHTMLAttributes, type KeyboardEvent, type ReactNode } from "react";
import { Eye, EyeOff, TriangleAlert } from "lucide-react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "placeholder"> & {
  label: string;
  icon?: ElementType;
  error?: string | null;
  hint?: ReactNode;
};

/**
 * A text field with a floating label, a leading icon, a focus glow, an inline error, and (for
 * passwords) a show/hide toggle and a Caps Lock warning.
 *
 * Text and background colors are set EXPLICITLY for light and dark: relying on inherited colors
 * is what once made typed text invisible in dark mode. The floating label works off the
 * browser's :placeholder-shown state, hence the single-space placeholder.
 */
export function AuthField({ label, icon: Icon, error, hint, type = "text", className = "", onKeyDown, onKeyUp, onBlur, ...rest }: Props) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const [revealed, setRevealed] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const isPassword = type === "password";

  function trackCaps(e: KeyboardEvent<HTMLInputElement>) {
    if (isPassword && typeof e.getModifierState === "function") setCapsLock(e.getModifierState("CapsLock"));
  }

  const describedBy = [error ? errorId : null, hint && !error ? hintId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className={className}>
      <div className="relative">
        <input
          id={id}
          type={isPassword && revealed ? "text" : type}
          placeholder=" "
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          onKeyDown={(e) => {
            trackCaps(e);
            onKeyDown?.(e);
          }}
          onKeyUp={(e) => {
            trackCaps(e);
            onKeyUp?.(e);
          }}
          onBlur={(e) => {
            setCapsLock(false);
            onBlur?.(e);
          }}
          className={`peer block w-full rounded-xl border bg-white pb-2 pt-6 text-sm text-slate-900 shadow-sm outline-none transition
            placeholder-transparent focus:ring-4 dark:bg-zinc-900 dark:text-white
            ${Icon ? "pl-11" : "pl-4"} ${isPassword ? "pr-12" : "pr-4"}
            ${
              error
                ? "border-red-400 focus:border-red-500 focus:ring-red-500/15 dark:border-red-500/70"
                : "border-slate-300 focus:border-indigo-500 focus:ring-indigo-500/15 dark:border-zinc-700 dark:focus:border-indigo-400"
            }`}
          {...rest}
        />
        {/* after the input on purpose: peer-focus only reaches later siblings */}
        {Icon && (
          <Icon
            aria-hidden
            size={18}
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 transition-colors peer-focus:text-indigo-500 dark:peer-focus:text-indigo-400 dark:text-zinc-500"
          />
        )}
        <label
          htmlFor={id}
          className={`pointer-events-none absolute top-3 text-[11px] font-medium text-slate-500 transition-all duration-200 dark:text-zinc-400
            ${Icon ? "left-11" : "left-4"}
            peer-placeholder-shown:top-1/2 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:text-sm peer-placeholder-shown:font-normal
            peer-focus:!top-3 peer-focus:!translate-y-0 peer-focus:!text-[11px] peer-focus:!font-medium peer-focus:text-indigo-600 dark:peer-focus:text-indigo-400
            peer-[:-webkit-autofill]:!top-3 peer-[:-webkit-autofill]:!translate-y-0 peer-[:-webkit-autofill]:!text-[11px]`}
        >
          {label}
        </label>
        {isPassword && (
          <button
            type="button"
            onClick={() => setRevealed((r) => !r)}
            aria-label={revealed ? "Hide password" : "Show password"}
            aria-pressed={revealed}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            {revealed ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        )}
      </div>

      {capsLock && (
        <p role="status" className="mt-1.5 flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
          <TriangleAlert size={13} aria-hidden /> Caps Lock is on
        </p>
      )}
      {error ? (
        <p id={errorId} role="alert" className="mt-1.5 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : (
        hint && (
          <div id={hintId} className="mt-1.5 text-xs text-slate-500 dark:text-zinc-500">
            {hint}
          </div>
        )
      )}
    </div>
  );
}

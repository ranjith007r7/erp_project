"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/api";

type SearchResult = {
  type: string;
  module: string;
  id: string;
  title: string;
  subtitle: string | null;
};

// Where each result type's module page lives - search doesn't have a
// dedicated detail page per record, so clicking a result takes you to
// that module's list page, matching how every other cross-link in this
// app already works (Notifications, the Dashboard's module tiles).
const MODULE_PATHS: Record<string, string> = {
  crm: "/crm",
  sales: "/sales",
  hr: "/hr",
  procurement: "/procurement",
  documents: "/documents",
};

export function GlobalSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function handleChange(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (value.trim().length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }

    // Debounced, not fired on every keystroke - avoids hammering the
    // backend (and the multiple ILIKE queries it runs per module) while
    // someone is still actively typing.
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await apiRequest<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(value.trim())}`, { auth: true });
        setResults(data.results);
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  }

  function handleResultClick(result: SearchResult) {
    setOpen(false);
    setQuery("");
    const path = MODULE_PATHS[result.module];
    if (path) router.push(path);
  }

  return (
    <div className="relative w-full max-w-md" ref={containerRef}>
      <input
        type="text"
        placeholder="Search leads, customers, products, employees…"
        value={query}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={() => query.trim().length >= 2 && setOpen(true)}
        className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-zinc-500 rounded-lg px-3 py-2 text-sm"
      />

      {open && (
        <div className="absolute left-0 right-0 mt-1 bg-white dark:bg-zinc-900 rounded-lg shadow-lg dark:shadow-none border border-slate-100 dark:border-zinc-800 z-50 max-h-96 overflow-y-auto">
          {loading && <p className="p-3 text-xs text-slate-400 dark:text-zinc-500">Searching…</p>}
          {!loading && results.length === 0 && (
            <p className="p-3 text-xs text-slate-400 dark:text-zinc-500">No matches for &quot;{query}&quot;.</p>
          )}
          {!loading &&
            results.map((r) => (
              <button
                key={`${r.type}-${r.id}`}
                onClick={() => handleResultClick(r)}
                className="w-full text-left px-3 py-2 hover:bg-slate-50 dark:hover:bg-zinc-800 border-b border-slate-50 dark:border-zinc-800 last:border-0"
              >
                <p className="text-sm text-slate-800 dark:text-white">{r.title}</p>
                <p className="text-xs text-slate-400 dark:text-zinc-500">
                  {r.type} {r.subtitle && `· ${r.subtitle}`}
                </p>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

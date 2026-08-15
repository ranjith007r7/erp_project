"use client";

import { useMemo, useState } from "react";

/**
 * Client-side pagination for lists that are already fully loaded (every
 * module here fetches its whole list in one call, no server-side paging
 * exists yet). Deliberately generic — pass any array, get back the
 * current page's slice plus the controls to render. Reusable anywhere a
 * list crosses the roadmap's ~20-row threshold, not just Inventory.
 */
export function usePagination<T>(items: T[], pageSize = 10) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, totalPages);

  const pageItems = useMemo(
    () => items.slice((safePage - 1) * pageSize, safePage * pageSize),
    [items, safePage, pageSize]
  );

  return { pageItems, page: safePage, totalPages, setPage, totalItems: items.length };
}

export function PaginationControls({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex justify-center items-center gap-3 py-3 text-sm">
      <button
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        className="text-slate-500 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        ← Prev
      </button>
      <span className="text-slate-400 text-xs">
        Page {page} of {totalPages}
      </span>
      <button
        onClick={() => onChange(page + 1)}
        disabled={page >= totalPages}
        className="text-slate-500 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        Next →
      </button>
    </div>
  );
}

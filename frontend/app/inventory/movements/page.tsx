"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { PaginationControls } from "@/components/Pagination";
import { SkeletonList } from "@/components/Skeleton";

type Movement = {
  id: string; product_id: string; product_name: string; movement_type: "in" | "out"; qty: number; ref_type: string | null;
  date: string; title: string; details: { label: string; value: string }[]; link: string | null;
};
type Page = { total: number; page: number; page_size: number; total_pages: number; items: Movement[] };
type Product = { id: string; name: string };

export default function StockMovementsPage() {
  const [data, setData] = useState<Page | null>(null);
  const [page, setPage] = useState(1);
  const [direction, setDirection] = useState("");
  const [productId, setProductId] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const sel = "border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm";

  useEffect(() => { apiRequest<Product[]>("/api/sales/products", { auth: true }).then(setProducts).catch(() => {}); }, []);
  const load = useCallback(() => {
    const qs = new URLSearchParams({ page: String(page), page_size: "15" });
    if (direction) qs.set("direction", direction);
    if (productId) qs.set("product_id", productId);
    apiRequest<Page>(`/api/inventory/movements/page?${qs}`, { auth: true }).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  }, [page, direction, productId]);
  useEffect(load, [load]);

  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Stock Movements" description="Every unit that went in or out of Inventory, newest first, with the job, client, person and (if you may see it) profit behind it." backHref="/inventory" backLabel="← Inventory" />
      <div className="flex flex-wrap gap-2 mb-4">
        <select aria-label="Direction" className={sel} value={direction} onChange={(e) => { setDirection(e.target.value); setPage(1); }}>
          <option value="">In and out</option><option value="in">Stock in</option><option value="out">Stock out</option>
        </select>
        <select aria-label="Product" className={sel} value={productId} onChange={(e) => { setProductId(e.target.value); setPage(1); }}>
          <option value="">All products</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        {data && <span className="self-center text-xs text-slate-500 dark:text-zinc-400">{data.total} movement{data.total === 1 ? "" : "s"}</span>}
      </div>
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {!data ? <SkeletonList rows={5} /> : (
        <>
          <div className="space-y-2" data-testid="movement-list">
            {data.items.map((m) => (
              <div key={m.id} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-3" data-testid="movement">
                <div className="flex justify-between items-start gap-3">
                  <div>
                    <p className="font-medium text-slate-800 dark:text-white">{m.product_name}</p>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">{m.title} · {m.date}</p>
                  </div>
                  <span className={`font-semibold tabular-nums ${m.movement_type === "in" ? "text-green-600" : "text-orange-600"}`}>{m.movement_type === "in" ? "+" : "-"}{m.qty}</span>
                </div>
                {m.details.length > 0 && (
                  <dl className="mt-2 grid sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1 text-xs">
                    {m.details.map((d) => (<div key={d.label} className="flex gap-1.5"><dt className="text-slate-500 dark:text-zinc-400">{d.label}:</dt><dd className="text-slate-800 dark:text-zinc-100 font-medium">{d.value}</dd></div>))}
                  </dl>
                )}
                {m.link && <Link href={m.link} className="inline-block mt-2 text-xs underline text-slate-600 dark:text-zinc-300">Open</Link>}
              </div>
            ))}
            {data.items.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No stock movements yet.</p>}
          </div>
          <PaginationControls page={data.page} totalPages={data.total_pages} onChange={setPage} />
        </>
      )}
    </main>
  );
}

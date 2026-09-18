"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { apiRequest } from "@/lib/api";
import { PageHeader, Card } from "@/components/ui";
import { SkeletonList } from "@/components/Skeleton";
import { Search as SearchIcon } from "lucide-react";

type SearchResult = { type: string; module: string; id: string; title: string; subtitle: string | null };

const MODULE_PATHS: Record<string, string> = {
  crm: "/crm",
  sales: "/sales",
  hr: "/hr",
  procurement: "/procurement",
  documents: "/documents",
};

const TYPE_LABELS: Record<string, string> = {
  lead: "Lead",
  account: "Account",
  customer: "Customer",
  product: "Product",
  employee: "Employee",
  vendor: "Vendor",
  document: "Document",
};

function SearchResultsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = searchParams.get("q") || "";
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    apiRequest<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(q)}&full=true`, { auth: true })
      .then((data) => setResults(data.results))
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
  }, [q]);

  // Grouped by module so results read as sections ("CRM", "Sales", ...)
  // rather than one flat, hard-to-scan list mixing every type together -
  // the header dropdown can get away with a flat list since it's
  // deliberately short (5 per type); a real results page with up to
  // 50 per type genuinely needs structure.
  const grouped = results.reduce<Record<string, SearchResult[]>>((acc, r) => {
    (acc[r.module] ||= []).push(r);
    return acc;
  }, {});

  return (
    <main className="min-h-screen p-8">
      <PageHeader title={`Search results for "${q}"`} description={`${results.length} match${results.length === 1 ? "" : "es"}`} />

      {loading && <SkeletonList rows={5} />}

      {!loading && results.length === 0 && (
        <Card className="p-8 text-center max-w-md">
          <SearchIcon className="mx-auto mb-2 text-slate-300 dark:text-zinc-600" size={32} />
          <p className="text-sm text-slate-500 dark:text-zinc-400">
            {q.trim().length < 2 ? "Type at least 2 characters to search." : `No matches for "${q}".`}
          </p>
        </Card>
      )}

      {!loading && results.length > 0 && (
        <div className="space-y-6 max-w-2xl">
          {Object.entries(grouped).map(([module, items]) => (
            <div key={module}>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-zinc-500 mb-2">
                {module} · {items.length}
              </h2>
              <Card className="divide-y dark:divide-zinc-800">
                {items.map((r) => (
                  <button
                    key={`${r.type}-${r.id}`}
                    onClick={() => router.push(MODULE_PATHS[r.module] || "/dashboard")}
                    className="w-full text-left px-4 py-3 hover:bg-slate-50 dark:hover:bg-zinc-800 transition-colors"
                  >
                    <p className="text-sm text-slate-800 dark:text-white">{r.title}</p>
                    <p className="text-xs text-slate-400 dark:text-zinc-500">
                      {TYPE_LABELS[r.type] || r.type} {r.subtitle && `· ${r.subtitle}`}
                    </p>
                  </button>
                ))}
              </Card>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}

export default function SearchResultsPage() {
  return (
    <Suspense fallback={<main className="min-h-screen p-8"><SkeletonList rows={5} /></main>}>
      <SearchResultsContent />
    </Suspense>
  );
}

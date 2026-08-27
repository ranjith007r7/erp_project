"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { CustomFieldsSection } from "@/components/CustomFieldsSection";
import { PageHeader } from "@/components/ui";
import { usePagination, PaginationControls } from "@/components/Pagination";

type Category = { id: string; name: string };
type Product = { id: string; name: string; sku: string | null; unit_price: string; reorder_level: number };
type StockLevel = { product_id: string; quantity: number };
type Movement = { id: string; product_id: string; movement_type: string; qty: number; ref_type: string | null; date: string };

export default function InventoryPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [stockLevels, setStockLevels] = useState<StockLevel[]>([]);
  const [movements, setMovements] = useState<Movement[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [categoryForm, setCategoryForm] = useState({ name: "" });
  const [productForm, setProductForm] = useState({ name: "", sku: "", unit_price: "", reorder_level: "0", category_id: "" });
  const [expandedProductId, setExpandedProductId] = useState<string | null>(null);
  const { pageItems: pagedProducts, page: productPage, totalPages: productTotalPages, setPage: setProductPage } =
    usePagination(products, 10);

  function loadAll() {
    apiRequest<Category[]>("/api/inventory/categories", { auth: true }).then(setCategories).catch(() => {});
    apiRequest<Product[]>("/api/sales/products", { auth: true }).then(setProducts).catch((e) => setError(e.message));
    apiRequest<StockLevel[]>("/api/inventory/stock-levels", { auth: true }).then(setStockLevels).catch(() => {});
    apiRequest<Movement[]>("/api/inventory/movements", { auth: true }).then(setMovements).catch(() => {});
  }

  useEffect(loadAll, []);

  function stockFor(productId: string) {
    const level = stockLevels.find((s) => s.product_id === productId);
    return level ? level.quantity : 0;
  }

  async function addCategory(e: React.FormEvent) {
    e.preventDefault();
    await apiRequest("/api/inventory/categories", { method: "POST", auth: true, body: categoryForm }).catch((err) => setError(err.message));
    setCategoryForm({ name: "" });
    loadAll();
  }

  async function addProduct(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/sales/products", {
        method: "POST",
        auth: true,
        body: {
          name: productForm.name,
          sku: productForm.sku || null,
          unit_price: Number(productForm.unit_price),
          reorder_level: Number(productForm.reorder_level),
          category_id: productForm.category_id || null,
        },
      });
      setProductForm({ name: "", sku: "", unit_price: "", reorder_level: "0", category_id: "" });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add product");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Inventory" />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-2 gap-6 mb-8">
        <form onSubmit={addCategory} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Add Category</h2>
          <input
            placeholder="Category name"
            required
            value={categoryForm.name}
            onChange={(e) => setCategoryForm({ name: e.target.value })}
            className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
          />
          <button className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 dark:hover:bg-zinc-300">
            Add Category
          </button>
        </form>

        <form onSubmit={addProduct} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Add Product</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input
              placeholder="Name"
              required
              value={productForm.name}
              onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
              className="border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="SKU"
              value={productForm.sku}
              onChange={(e) => setProductForm({ ...productForm, sku: e.target.value })}
              className="border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Unit price"
              type="number"
              required
              value={productForm.unit_price}
              onChange={(e) => setProductForm({ ...productForm, unit_price: e.target.value })}
              className="border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Reorder level"
              type="number"
              value={productForm.reorder_level}
              onChange={(e) => setProductForm({ ...productForm, reorder_level: e.target.value })}
              className="border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <select
            value={productForm.category_id}
            onChange={(e) => setProductForm({ ...productForm, category_id: e.target.value })}
            className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
          >
            <option value="">No category</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <button className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 dark:hover:bg-zinc-300">
            Add Product
          </button>
        </form>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Products & Stock</h2>
          <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm divide-y">
            {pagedProducts.map((p) => {
              const qty = stockFor(p.id);
              const low = qty <= p.reorder_level;
              const expanded = expandedProductId === p.id;
              return (
                <div key={p.id} className="p-3 text-sm">
                  <div className="flex justify-between items-center">
                    <div>
                      <p className="text-slate-800 dark:text-white font-medium">{p.name}</p>
                      <p className="text-xs text-slate-500 dark:text-zinc-500">{p.sku || "no SKU"} · ₹{p.unit_price}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={low ? "text-red-600 font-semibold text-xs" : "text-slate-500 dark:text-zinc-500 text-xs"}>
                        {qty} in stock {low && "· LOW"}
                      </span>
                      <button
                        onClick={() => setExpandedProductId(expanded ? null : p.id)}
                        className="text-xs text-slate-400 dark:text-zinc-500 underline hover:text-slate-600 dark:hover:text-zinc-300"
                      >
                        {expanded ? "Hide fields" : "Fields"}
                      </button>
                    </div>
                  </div>
                  {expanded && <CustomFieldsSection entityType="product" entityId={p.id} />}
                </div>
              );
            })}
            {products.length === 0 && <p className="p-3 text-sm text-slate-400 dark:text-zinc-500">No products yet.</p>}
          </div>
          <PaginationControls page={productPage} totalPages={productTotalPages} onChange={setProductPage} />
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Stock Movements</h2>
          <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm divide-y">
            {movements.map((m) => (
              <div key={m.id} className="p-3 flex justify-between items-center text-sm">
                <span className="text-slate-700 dark:text-zinc-200">
                  {products.find((p) => p.id === m.product_id)?.name || "Unknown product"}
                </span>
                <span className={m.movement_type === "in" ? "text-green-600" : "text-orange-600"}>
                  {m.movement_type === "in" ? "+" : "-"}{m.qty} · {m.ref_type}
                </span>
              </div>
            ))}
            {movements.length === 0 && <p className="p-3 text-sm text-slate-400 dark:text-zinc-500">No stock movements yet.</p>}
          </div>
        </section>
      </div>
    </main>
  );
}

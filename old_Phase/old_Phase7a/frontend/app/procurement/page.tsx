"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";

type Vendor = { id: string; name: string };
type Product = { id: string; name: string; unit_price: string };
type POItem = { product_id: string; qty: number; unit_price: string };
type PurchaseOrder = { id: string; vendor_id: string; total: string; status: string; items: POItem[] };

export default function ProcurementPage() {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [vendorForm, setVendorForm] = useState({ name: "" });
  const [poForm, setPoForm] = useState({ vendor_id: "", product_id: "", qty: "1", unit_price: "" });

  function loadAll() {
    apiRequest<Vendor[]>("/api/procurement/vendors", { auth: true }).then(setVendors).catch(() => {});
    apiRequest<Product[]>("/api/sales/products", { auth: true }).then(setProducts).catch(() => {});
    apiRequest<PurchaseOrder[]>("/api/procurement/purchase-orders", { auth: true }).then(setOrders).catch((e) => setError(e.message));
  }

  useEffect(loadAll, []);

  function vendorName(id: string) {
    return vendors.find((v) => v.id === id)?.name || id.slice(0, 8);
  }

  async function addVendor(e: React.FormEvent) {
    e.preventDefault();
    await apiRequest("/api/procurement/vendors", { method: "POST", auth: true, body: vendorForm }).catch((err) => setError(err.message));
    setVendorForm({ name: "" });
    loadAll();
  }

  async function createPO(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/procurement/purchase-orders", {
        method: "POST",
        auth: true,
        body: {
          vendor_id: poForm.vendor_id,
          items: [{ product_id: poForm.product_id, qty: Number(poForm.qty), unit_price: Number(poForm.unit_price) }],
        },
      });
      setPoForm({ vendor_id: "", product_id: "", qty: "1", unit_price: "" });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create purchase order");
    }
  }

  async function receivePO(id: string) {
    try {
      await apiRequest(`/api/procurement/purchase-orders/${id}/receive`, { method: "POST", auth: true });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to receive purchase order");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Procurement</h1>
        <Link href="/dashboard" className="text-sm text-slate-500 underline">
          ← Dashboard
        </Link>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-2 gap-6 mb-8">
        <form onSubmit={addVendor} className="bg-white rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 text-sm">Add Vendor</h2>
          <input
            placeholder="Vendor name"
            required
            value={vendorForm.name}
            onChange={(e) => setVendorForm({ name: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
          <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
            Add Vendor
          </button>
        </form>

        <form onSubmit={createPO} className="bg-white rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 text-sm">Create Purchase Order</h2>
          <select
            required
            value={poForm.vendor_id}
            onChange={(e) => setPoForm({ ...poForm, vendor_id: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select vendor...</option>
            {vendors.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
          <select
            required
            value={poForm.product_id}
            onChange={(e) => setPoForm({ ...poForm, product_id: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select product...</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <div className="grid grid-cols-2 gap-2">
            <input
              placeholder="Qty"
              type="number"
              min={1}
              value={poForm.qty}
              onChange={(e) => setPoForm({ ...poForm, qty: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Unit cost"
              type="number"
              required
              value={poForm.unit_price}
              onChange={(e) => setPoForm({ ...poForm, unit_price: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
            Create Purchase Order
          </button>
        </form>
      </div>

      <section>
        <h2 className="font-semibold text-slate-700 mb-3">Purchase Orders</h2>
        <div className="space-y-2">
          {orders.map((po) => (
            <div key={po.id} className="bg-white rounded-lg shadow-sm p-3 flex justify-between items-center">
              <div>
                <p className="text-sm font-medium text-slate-800">{vendorName(po.vendor_id)}</p>
                <p className="text-xs text-slate-500">₹{Number(po.total).toLocaleString("en-IN")} · {po.status}</p>
              </div>
              {po.status !== "received" && (
                <button
                  onClick={() => receivePO(po.id)}
                  className="text-xs bg-slate-800 text-white px-3 py-1.5 rounded-lg hover:bg-slate-700"
                >
                  Receive Goods
                </button>
              )}
            </div>
          ))}
          {orders.length === 0 && <p className="text-sm text-slate-400">No purchase orders yet.</p>}
        </div>
      </section>
    </main>
  );
}

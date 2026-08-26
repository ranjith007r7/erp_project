"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { usePagination, PaginationControls } from "@/components/Pagination";

type Product = { id: string; name: string; unit_price: string };
type Customer = { id: string; name: string };
type QuotationItem = { product_id: string; qty: number; unit_price: string };
type Quotation = { id: string; customer_id: string; total: string; status: string; items: QuotationItem[] };
type SalesOrder = { id: string; customer_id: string; total: string; status: string };
type Invoice = { id: string; order_id: string; amount: string; status: string };

export default function SalesPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [quotations, setQuotations] = useState<Quotation[]>([]);
  const [orders, setOrders] = useState<SalesOrder[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const { pageItems: pagedInvoices, page: invoicePage, totalPages: invoiceTotalPages, setPage: setInvoicePage } = usePagination(invoices, 10);
  const [error, setError] = useState<string | null>(null);

  const [productForm, setProductForm] = useState({ name: "", unit_price: "" });
  const [customerForm, setCustomerForm] = useState({ name: "" });
  const [quoteForm, setQuoteForm] = useState({ customer_id: "", product_id: "", qty: "1", unit_price: "" });

  function loadAll() {
    apiRequest<Product[]>("/api/sales/products", { auth: true }).then(setProducts).catch(() => {});
    apiRequest<Customer[]>("/api/sales/customers", { auth: true }).then(setCustomers).catch(() => {});
    apiRequest<Quotation[]>("/api/sales/quotations", { auth: true }).then(setQuotations).catch((e) => setError(e.message));
    apiRequest<SalesOrder[]>("/api/sales/orders", { auth: true }).then(setOrders).catch(() => {});
    apiRequest<Invoice[]>("/api/sales/invoices", { auth: true }).then(setInvoices).catch(() => {});
  }

  useEffect(loadAll, []);

  async function addProduct(e: React.FormEvent) {
    e.preventDefault();
    await apiRequest("/api/sales/products", {
      method: "POST",
      auth: true,
      body: { name: productForm.name, unit_price: Number(productForm.unit_price) },
    }).catch((err) => setError(err.message));
    setProductForm({ name: "", unit_price: "" });
    loadAll();
  }

  async function addCustomer(e: React.FormEvent) {
    e.preventDefault();
    await apiRequest("/api/sales/customers", {
      method: "POST",
      auth: true,
      body: { name: customerForm.name },
    }).catch((err) => setError(err.message));
    setCustomerForm({ name: "" });
    loadAll();
  }

  async function createQuotation(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/sales/quotations", {
        method: "POST",
        auth: true,
        body: {
          customer_id: quoteForm.customer_id,
          items: [
            {
              product_id: quoteForm.product_id,
              qty: Number(quoteForm.qty),
              unit_price: Number(quoteForm.unit_price),
            },
          ],
        },
      });
      setQuoteForm({ customer_id: "", product_id: "", qty: "1", unit_price: "" });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create quotation");
    }
  }

  async function acceptQuotation(id: string) {
    try {
      await apiRequest(`/api/sales/quotations/${id}/accept`, { method: "POST", auth: true });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to accept quotation");
    }
  }

  async function generateInvoice(orderId: string) {
    try {
      await apiRequest(`/api/sales/orders/${orderId}/invoice`, { method: "POST", auth: true });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate invoice");
    }
  }

  function customerName(id: string) {
    return customers.find((c) => c.id === id)?.name || id.slice(0, 8);
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Sales" />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-2 gap-6 mb-8">
        <form onSubmit={addProduct} className="bg-white rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 text-sm">Add Product</h2>
          <input
            placeholder="Product name"
            required
            value={productForm.name}
            onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
          <input
            placeholder="Unit price"
            required
            type="number"
            value={productForm.unit_price}
            onChange={(e) => setProductForm({ ...productForm, unit_price: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
          <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
            Add Product
          </button>
        </form>

        <form onSubmit={addCustomer} className="bg-white rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 text-sm">Add Customer</h2>
          <input
            placeholder="Customer name"
            required
            value={customerForm.name}
            onChange={(e) => setCustomerForm({ name: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
          <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
            Add Customer
          </button>
        </form>
      </div>

      <form onSubmit={createQuotation} className="bg-white rounded-xl shadow-sm p-4 mb-8 grid md:grid-cols-5 gap-2 items-end">
        <div className="md:col-span-2">
          <label className="text-xs text-slate-500">Customer</label>
          <select
            required
            value={quoteForm.customer_id}
            onChange={(e) => setQuoteForm({ ...quoteForm, customer_id: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select...</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div className="md:col-span-2">
          <label className="text-xs text-slate-500">Product</label>
          <select
            required
            value={quoteForm.product_id}
            onChange={(e) => {
              const p = products.find((p) => p.id === e.target.value);
              setQuoteForm({ ...quoteForm, product_id: e.target.value, unit_price: p?.unit_price || "" });
            }}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select...</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name} (₹{p.unit_price})</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-500">Qty</label>
          <input
            type="number"
            min={1}
            value={quoteForm.qty}
            onChange={(e) => setQuoteForm({ ...quoteForm, qty: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
        </div>
        <button className="bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
          Create Quote
        </button>
      </form>

      <div className="grid md:grid-cols-3 gap-6">
        <section>
          <h2 className="font-semibold text-slate-700 mb-3">Quotations</h2>
          <div className="space-y-2">
            {quotations.map((q) => (
              <div key={q.id} className="bg-white rounded-lg shadow-sm p-3">
                <p className="text-sm font-medium text-slate-800">{customerName(q.customer_id)}</p>
                <p className="text-xs text-slate-500">₹{Number(q.total).toLocaleString("en-IN")} · {q.status}</p>
                {q.status !== "accepted" && (
                  <button
                    onClick={() => acceptQuotation(q.id)}
                    className="mt-2 text-xs bg-slate-800 text-white px-3 py-1.5 rounded-lg hover:bg-slate-700"
                  >
                    Accept → Sales Order
                  </button>
                )}
              </div>
            ))}
            {quotations.length === 0 && <p className="text-sm text-slate-400">No quotations yet.</p>}
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 mb-3">Sales Orders</h2>
          <div className="space-y-2">
            {orders.map((o) => (
              <div key={o.id} className="bg-white rounded-lg shadow-sm p-3">
                <p className="text-sm font-medium text-slate-800">{customerName(o.customer_id)}</p>
                <p className="text-xs text-slate-500">₹{Number(o.total).toLocaleString("en-IN")} · {o.status}</p>
                {o.status !== "fulfilled" && (
                  <button
                    onClick={() => generateInvoice(o.id)}
                    className="mt-2 text-xs bg-slate-800 text-white px-3 py-1.5 rounded-lg hover:bg-slate-700"
                  >
                    Generate Invoice
                  </button>
                )}
              </div>
            ))}
            {orders.length === 0 && <p className="text-sm text-slate-400">No sales orders yet.</p>}
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 mb-3">Invoices</h2>
          <div className="space-y-2">
            {pagedInvoices.map((inv) => (
              <div key={inv.id} className="bg-white rounded-lg shadow-sm p-3">
                <p className="text-sm font-medium text-slate-800">
                  ₹{Number(inv.amount).toLocaleString("en-IN")}
                </p>
                <p className="text-xs text-slate-500">{inv.status}</p>
              </div>
            ))}
            {invoices.length === 0 && <p className="text-sm text-slate-400">No invoices yet.</p>}
          </div>
          <PaginationControls page={invoicePage} totalPages={invoiceTotalPages} onChange={setInvoicePage} />
        </section>
      </div>
    </main>
  );
}

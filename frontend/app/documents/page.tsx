"use client";

import { useEffect, useState } from "react";
import { apiRequest, apiUpload } from "@/lib/api";
import { NotificationBell } from "@/components/NotificationBell";
import { PageHeader, Button } from "@/components/ui";

type Doc = { id: string; title: string; file_url: string | null; storage_key: string | null; related_type: string | null };
type Workflow = { id: string; name: string; module: string };
type Step = { step_order: number; role_required: string; status: string };
type ApprovalRequest = { id: string; entity_type: string; status: string; steps: Step[] };

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [docForm, setDocForm] = useState({ title: "", file_url: "" });
  const [addDocMode, setAddDocMode] = useState<"upload" | "link">("upload");
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [workflowForm, setWorkflowForm] = useState({ name: "", module: "", step1: "", step2: "" });
  const [entityForm, setEntityForm] = useState({ workflow_id: "", entity_type: "" });

  function loadAll() {
    apiRequest<Doc[]>("/api/documents", { auth: true }).then(setDocuments).catch((e) => setError(e.message));
    apiRequest<Workflow[]>("/api/documents/workflows", { auth: true }).then(setWorkflows).catch(() => {});
    apiRequest<ApprovalRequest[]>("/api/documents/approval-requests", { auth: true }).then(setRequests).catch(() => {});
  }

  useEffect(loadAll, []);

  async function addDocument(e: React.FormEvent) {
    e.preventDefault();
    await apiRequest("/api/documents", { method: "POST", auth: true, body: docForm }).catch((err) => setError(err.message));
    setDocForm({ title: "", file_url: "" });
    loadAll();
  }

  async function handleFileUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!uploadFile) return;
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("title", uploadTitle);
      formData.append("file", uploadFile);
      await apiUpload("/api/documents/upload", formData);
      setUploadTitle("");
      setUploadFile(null);
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDownload(doc: Doc) {
    setError(null);
    if (doc.storage_key) {
      // A real upload - get a FRESH presigned URL (they expire after
      // 10 minutes, so this can't be cached from an earlier load) and
      // open it directly; the browser talks to R2 from here on, not
      // back through our API.
      try {
        const result = await apiRequest<{ url: string }>(`/api/documents/${doc.id}/download`, { auth: true });
        window.open(result.url, "_blank");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not generate a download link");
      }
    } else if (doc.file_url) {
      window.open(doc.file_url, "_blank");
    }
  }

  async function addWorkflow(e: React.FormEvent) {
    e.preventDefault();
    const steps = [workflowForm.step1, workflowForm.step2].filter(Boolean).map((role) => ({ role }));
    try {
      await apiRequest("/api/documents/workflows", {
        method: "POST",
        auth: true,
        body: { name: workflowForm.name, module: workflowForm.module, steps },
      });
      setWorkflowForm({ name: "", module: "", step1: "", step2: "" });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add workflow");
    }
  }

  async function createRequest(e: React.FormEvent) {
    e.preventDefault();
    // Demo entity_id since this page isn't wired to a specific real record yet
    const entity_id = "00000000-0000-0000-0000-000000000000".replace(/0/g, () => Math.floor(Math.random() * 10).toString());
    try {
      await apiRequest("/api/documents/approval-requests", {
        method: "POST",
        auth: true,
        body: { workflow_id: entityForm.workflow_id, entity_type: entityForm.entity_type, entity_id },
      });
      setEntityForm({ workflow_id: "", entity_type: "" });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create approval request");
    }
  }

  async function actionRequest(id: string, decision: "approve" | "reject") {
    await apiRequest(`/api/documents/approval-requests/${id}/action`, { method: "POST", auth: true, body: { decision } })
      .catch((err) => setError(err instanceof Error ? err.message : "Action failed"));
    loadAll();
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Documents & Workflow Approvals" actions={<NotificationBell />} />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-3 gap-6 mb-8">
        <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-2">
          <div className="flex justify-between items-center">
            <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Add Document</h2>
            <div className="flex text-xs rounded-lg overflow-hidden border border-slate-300 dark:border-zinc-700">
              <button
                type="button"
                onClick={() => setAddDocMode("upload")}
                className={`px-2 py-1 ${addDocMode === "upload" ? "bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900" : "bg-white dark:bg-zinc-900 text-slate-600 dark:text-zinc-300"}`}
              >
                Upload File
              </button>
              <button
                type="button"
                onClick={() => setAddDocMode("link")}
                className={`px-2 py-1 ${addDocMode === "link" ? "bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900" : "bg-white dark:bg-zinc-900 text-slate-600 dark:text-zinc-300"}`}
              >
                Paste a Link
              </button>
            </div>
          </div>

          {addDocMode === "upload" ? (
            <form onSubmit={handleFileUpload} className="space-y-2">
              <input
                placeholder="Title"
                required
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm"
              />
              <input
                type="file"
                required
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm"
              />
              <p className="text-xs text-slate-400 dark:text-zinc-500">PDF, Office docs, or images, up to 10MB.</p>
              <Button type="submit" disabled={uploading} className="w-full">
                {uploading ? "Uploading..." : "Upload"}
              </Button>
            </form>
          ) : (
            <form onSubmit={addDocument} className="space-y-2">
              <input placeholder="Title" required value={docForm.title} onChange={(e) => setDocForm({ ...docForm, title: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm" />
              <input placeholder="File URL" required value={docForm.file_url} onChange={(e) => setDocForm({ ...docForm, file_url: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm" />
              <Button type="submit" className="w-full">Add Document</Button>
            </form>
          )}
        </div>

        <form onSubmit={addWorkflow} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Define Approval Workflow</h2>
          <input placeholder="Workflow name" required value={workflowForm.name} onChange={(e) => setWorkflowForm({ ...workflowForm, name: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm" />
          <input placeholder="Module (e.g. finance)" required value={workflowForm.module} onChange={(e) => setWorkflowForm({ ...workflowForm, module: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm" />
          <input placeholder="Step 1 role (e.g. Manager)" required value={workflowForm.step1} onChange={(e) => setWorkflowForm({ ...workflowForm, step1: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm" />
          <input placeholder="Step 2 role (optional)" value={workflowForm.step2} onChange={(e) => setWorkflowForm({ ...workflowForm, step2: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm" />
          <button className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 dark:hover:bg-zinc-300">Create Workflow</button>
        </form>

        <form onSubmit={createRequest} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Start Approval Request</h2>
          <select required value={entityForm.workflow_id} onChange={(e) => setEntityForm({ ...entityForm, workflow_id: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm">
            <option value="">Select workflow...</option>
            {workflows.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <input placeholder="What is this for? (e.g. Expense #123)" required value={entityForm.entity_type} onChange={(e) => setEntityForm({ ...entityForm, entity_type: e.target.value })} className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm" />
          <button className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 dark:hover:bg-zinc-300">Submit for Approval</button>
        </form>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Approval Requests</h2>
          <div className="space-y-2">
            {requests.map((r) => {
              const pendingStep = r.steps.find((s) => s.status === "pending");
              return (
                <div key={r.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3 text-sm">
                  <p className="text-slate-800 dark:text-white font-medium">{r.entity_type}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-500 mb-2">
                    Status: {r.status} ·{" "}
                    {r.steps.map((s) => `${s.role_required}(${s.status})`).join(" → ")}
                  </p>
                  {r.status === "pending" && pendingStep && (
                    <div className="flex gap-2">
                      <button onClick={() => actionRequest(r.id, "approve")} className="text-xs bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 px-3 py-1 rounded-lg hover:bg-slate-700 dark:hover:bg-zinc-300">
                        Approve ({pendingStep.role_required} step)
                      </button>
                      <button onClick={() => actionRequest(r.id, "reject")} className="text-xs border border-slate-300 dark:border-zinc-700 text-slate-600 dark:text-zinc-300 px-3 py-1 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800">
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
            {requests.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No approval requests yet.</p>}
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Documents</h2>
          <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm divide-y">
            {documents.map((d) => (
              <button
                key={d.id}
                onClick={() => handleDownload(d)}
                className="p-3 text-sm block w-full text-left hover:bg-slate-50 dark:hover:bg-zinc-800"
              >
                <p className="text-slate-800 dark:text-white">
                  {d.title} {d.storage_key && <span className="text-xs text-slate-400 dark:text-zinc-500">(uploaded)</span>}
                </p>
                <p className="text-xs text-slate-400 dark:text-zinc-500">{d.related_type || "general"}</p>
              </button>
            ))}
            {documents.length === 0 && <p className="p-3 text-sm text-slate-400 dark:text-zinc-500">No documents yet.</p>}
          </div>
        </section>
      </div>
    </main>
  );
}

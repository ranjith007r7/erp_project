"use client";

import { useState } from "react";
import { apiRequest, apiUpload } from "@/lib/api";
import { PageHeader, Card, Button } from "@/components/ui";
import { useTheme } from "@/components/ThemeProvider";
import { useToast } from "@/components/Toast";
import { Sun, Moon, ImageUp, Trash2 } from "lucide-react";

export default function AppearanceSettingsPage() {
  const { theme, toggleTheme } = useTheme();
  const { showToast } = useToast();
  const [brandingFile, setBrandingFile] = useState<File | null>(null);
  const [brandingUploading, setBrandingUploading] = useState(false);

  async function handleUploadBranding() {
    if (!brandingFile) return;
    setBrandingUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", brandingFile);
      await apiUpload("/api/organizations/branding", formData);
      showToast("Branding updated — every member of your organization will see it.", "success");
      setBrandingFile(null);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to update branding", "error");
    } finally {
      setBrandingUploading(false);
    }
  }

  async function handleRemoveBranding() {
    try {
      await apiRequest("/api/organizations/branding", { method: "DELETE", auth: true });
      showToast("Branding removed.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to remove branding", "error");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader
        title="Appearance"
        description="Personal display settings, and your organization's branding."
      />

      <div className="space-y-6 max-w-2xl">
        {/* Personal - light/dark, this browser only */}
        <Card className="p-4">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-100 text-sm mb-1">Theme</h2>
          <p className="text-xs text-slate-500 dark:text-zinc-500 mb-3">
            A personal preference, saved to this browser only — it doesn&apos;t affect what anyone else in your
            organization sees.
          </p>
          <Button variant="secondary" size="sm" onClick={toggleTheme} className="flex items-center gap-1.5">
            {theme === "light" ? <Moon size={14} /> : <Sun size={14} />}
            Switch to {theme === "light" ? "Dark" : "Light"}
          </Button>
        </Card>

        {/* Org-wide - admin-controlled, visible to every member */}
        <Card className="p-4">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-100 text-sm mb-1 flex items-center gap-1.5">
            <ImageUp size={16} /> Organization Branding
          </h2>
          <p className="text-xs text-slate-500 dark:text-zinc-500 mb-3">
            Upload a logo or background image. It replaces the default background for{" "}
            <span className="font-medium">every member of your organization</span>, not just you. Only Admins
            (or anyone granted &quot;Manage Roles &amp; Permissions&quot;) can change this — everyone else can only view it.
            Defaults to the light theme background regardless of your own dark/light setting above, since a
            custom image can look inconsistent against a dark background.
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setBrandingFile(e.target.files?.[0] ?? null)}
              className="text-xs text-slate-600 dark:text-zinc-300"
            />
            <Button size="sm" disabled={!brandingFile || brandingUploading} onClick={handleUploadBranding}>
              {brandingUploading ? "Uploading…" : "Upload"}
            </Button>
            <Button variant="danger" size="sm" onClick={handleRemoveBranding} className="flex items-center gap-1">
              <Trash2 size={14} /> Remove
            </Button>
          </div>
        </Card>
      </div>
    </main>
  );
}

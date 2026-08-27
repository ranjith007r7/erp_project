"use client";

import { useEffect, useState, type ReactNode } from "react";
import { apiRequest } from "@/lib/api";

/**
 * Wraps page content and applies the org's admin-uploaded background
 * image behind it, if one is set. Fetches a fresh presigned URL on
 * mount - see the backend route's own docstring for why that's fine
 * even though the URL expires after 10 minutes (a loaded image stays
 * rendered regardless; this only matters for the NEXT fetch).
 *
 * Distinct from ThemeProvider (light/dark) on purpose - this reflects
 * what an ADMIN chose for the whole org, not a personal preference, so
 * it isn't stored in localStorage at all, it's fetched fresh from the
 * backend every time.
 */
export function OrgBranding({ children }: { children: ReactNode }) {
  const [backgroundUrl, setBackgroundUrl] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<{ url: string | null }>("/api/organizations/branding", { auth: true })
      .then((data) => setBackgroundUrl(data.url))
      .catch(() => {}); // no branding set, or not logged in yet - fine, just show the default background
  }, []);

  return (
    <div
      className="min-h-screen relative"
      style={
        backgroundUrl
          ? { backgroundImage: `url(${backgroundUrl})`, backgroundSize: "cover", backgroundPosition: "center", backgroundAttachment: "fixed" }
          : undefined
      }
    >
      {/*
        A real contrast-safety measure, not just a note in the upload
        form's copy: an arbitrary admin-uploaded image could be any
        color or brightness, and page content (especially in dark mode)
        needs to stay legible regardless of what that image looks like.
        A translucent scrim - lighter in light mode, darker in dark
        mode - sits between the image and the content, so text contrast
        stays predictable no matter what the uploaded image contains.
        Only rendered at all when a background is actually set, so
        pages with no custom branding are completely unaffected.
      */}
      {backgroundUrl && (
        <div className="absolute inset-0 bg-white/70 dark:bg-slate-900/80 pointer-events-none" />
      )}
      <div className="relative">{children}</div>
    </div>
  );
}

"use client";

import { useEffect } from "react";
import Link from "next/link";

/**
 * Next.js's App Router automatically wraps every page in whichever
 * error.tsx is closest to it - this one at the app root catches any
 * uncaught render exception, anywhere in the app, that would otherwise
 * show the generic "Application error: a client-side exception has
 * occurred" blank page. Added after a real bug report: a stale-data race
 * on the Reports page (switching tabs before the new tab's data had
 * loaded) threw an unhandled exception that hit exactly this blank page.
 * That specific bug is fixed at the source in reports/page.tsx, but this
 * boundary stays as a permanent safety net for any future one.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="bg-white rounded-xl shadow-sm p-8 max-w-md text-center">
        <h1 className="text-xl font-bold text-slate-800 mb-2">Something went wrong</h1>
        <p className="text-sm text-slate-500 mb-6">
          This page hit an unexpected error. It's been logged to the browser console - if this
          keeps happening, that console output is exactly what to bring back for a fix.
        </p>
        <div className="flex gap-3 justify-center">
          <button
            onClick={reset}
            className="bg-slate-800 text-white text-sm px-4 py-2 rounded-lg hover:bg-slate-700"
          >
            Try again
          </button>
          <Link
            href="/dashboard"
            className="bg-slate-100 text-slate-700 text-sm px-4 py-2 rounded-lg hover:bg-slate-200"
          >
            Back to Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}

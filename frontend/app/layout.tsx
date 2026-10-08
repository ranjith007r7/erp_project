import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/Toast";
import { ThemeProvider } from "@/components/ThemeProvider";
import { OrgBranding } from "@/components/OrgBranding";
import { AppShell } from "@/components/AppShell";
import { BRAND } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: BRAND.productName, template: `%s · ${BRAND.productName}` },
  applicationName: BRAND.productName,
  description: `${BRAND.productName} by ${BRAND.companyName}: sales, finance, inventory, HR, projects and reporting in one workspace.`,
};

// Next.js App Router injects a sensible default viewport tag automatically,
// but making it explicit is safer than relying on that default silently
// continuing to hold across framework upgrades.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#4f46e5", // tints the browser toolbar on phones
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 dark:bg-black text-slate-900 dark:text-white transition-colors">
        <ThemeProvider>
          <ToastProvider>
            {/*
              Wrapped here, not per-page, so the org's background applies
              across the WHOLE authenticated portal, not just Dashboard -
              a real gap found through use (the original version only
              wrapped Dashboard). OrgBranding fetches silently-fails on
              pages before login (no token yet, e.g. /login, /signup) -
              harmless, just shows no background there, which is correct.
            */}
            <OrgBranding><AppShell>{children}</AppShell></OrgBranding>
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

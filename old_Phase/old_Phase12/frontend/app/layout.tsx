import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Base ERP",
  description: "Customizable base ERP platform",
};

// Next.js App Router injects a sensible default viewport tag automatically,
// but making it explicit is safer than relying on that default silently
// continuing to hold across framework upgrades.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

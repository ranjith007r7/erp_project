/**
 * Everything a client might want to rebrand, in ONE place and driven by
 * environment variables, so onboarding a new client is configuration, not code.
 *
 * These are PUBLIC build-time settings (NEXT_PUBLIC_*), not secrets. Set them in Vercel
 * (or in the terminal for a local run) and rebuild.
 *
 *   NEXT_PUBLIC_PRODUCT_NAME  what the product is called          (default "Ratoon ERP")
 *   NEXT_PUBLIC_COMPANY_NAME  the vendor, shown in the footer     (default "Ratoon Infotech")
 *   NEXT_PUBLIC_TAGLINE       one line under the product name     (default below)
 *   NEXT_PUBLIC_LOGO_URL      path or URL of the logo image       (default: a monogram of the
 *                             product name's first letter, drawn in code)
 *
 * Each variable must be read as a literal `process.env.NEXT_PUBLIC_X` for Next.js to
 * inline it at build time, so do not "tidy" these into a loop.
 */
export const BRAND = {
  productName: process.env.NEXT_PUBLIC_PRODUCT_NAME || "Ratoon ERP",
  companyName: process.env.NEXT_PUBLIC_COMPANY_NAME || "Ratoon Infotech",
  tagline: process.env.NEXT_PUBLIC_TAGLINE || "Run your whole business from one place.",
  logoUrl: process.env.NEXT_PUBLIC_LOGO_URL || "",
};

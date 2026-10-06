/**
 * Turns a company name into a subdomain suggestion that satisfies the server's rule
 * (lowercase letters, digits and hyphens; 2-63 characters; see OrganizationSignup).
 *   "Acme Corp."  -> "acme-corp"      "Ünïcode Co" -> "unicode-co"
 */
export function slugify(input: string, max = 63): string {
  return input
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "") // strip accents
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, max)
    .replace(/-+$/g, ""); // slicing can leave a trailing hyphen
}

/** What a person may type into the subdomain box: silently drops anything the server would reject. */
export function sanitizeSubdomain(input: string, max = 63): string {
  return input.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, max);
}

export function isValidSubdomain(value: string): boolean {
  return /^[a-z0-9-]+$/.test(value) && value.length >= 2 && value.length <= 63;
}

/**
 * Show timestamps in the organization's timezone (IST by default).
 *
 * WHY THIS EXISTS: the API sends timestamps WITHOUT a timezone marker (for example
 * "2026-10-05T08:35:29.123456") even though they are stored in UTC. JavaScript's
 * `new Date("2026-10-05T08:35:29")` treats a date-time with no marker as the BROWSER'S
 * LOCAL time, so the UTC clock reading was displayed unchanged: 8:35 AM when it was
 * 2:05 PM in India. The fix is to read marker-less values as UTC, then format them in
 * the display timezone explicitly.
 *
 * Set NEXT_PUBLIC_TIMEZONE (an IANA name such as "Asia/Dubai") to show another zone;
 * it is a public, non-secret setting. It defaults to Asia/Kolkata (IST).
 *
 * Use this for TIMESTAMPS only. Calendar dates with no time ("2026-10-05", such as a
 * due date) are not instants and must not be shifted by a timezone.
 */
export const DISPLAY_TIMEZONE = process.env.NEXT_PUBLIC_TIMEZONE || "Asia/Kolkata";

// Ends in "Z", or in an explicit offset such as "+05:30", "-0530" or "+00:00".
const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i;

export function parseApiTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null;
  const text = value.trim();
  if (!text) return null;
  const iso = HAS_ZONE.test(text) ? text : `${text.replace(" ", "T")}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined, timeZone: string = DISPLAY_TIMEZONE): string {
  const date = parseApiTimestamp(value);
  if (!date) return "—";
  try {
    return new Intl.DateTimeFormat("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
      timeZone,
      timeZoneName: "short",
    }).format(date);
  } catch {
    // An invalid NEXT_PUBLIC_TIMEZONE must never blank out the page.
    return date.toISOString();
  }
}

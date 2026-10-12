/** Client mobile numbers are exactly 10 digits: keep digits only, drop a pasted +91 / 91 / 0 prefix, cap at 10. */
export function tenDigits(v: string): string {
  let d = v.replace(/\D/g, "");
  if (d.length === 12 && d.startsWith("91")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  return d.slice(0, 10);
}

/**
 * An ADVISORY strength meter. The only rule the server enforces is a minimum length of 8
 * (see OrganizationSignup.admin_password), and that is the only thing that blocks signup;
 * this just nudges people toward a better password.
 */
export type Strength = {
  score: 0 | 1 | 2 | 3 | 4;
  label: "" | "Weak" | "Fair" | "Good" | "Strong";
  meetsMinimum: boolean;
};

export const MIN_PASSWORD_LENGTH = 8;

export function passwordStrength(password: string): Strength {
  if (!password) return { score: 0, label: "", meetsMinimum: false };
  const meetsMinimum = password.length >= MIN_PASSWORD_LENGTH;
  if (!meetsMinimum) return { score: 1, label: "Weak", meetsMinimum };

  let points = 0;
  if (password.length >= 12) points++;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) points++;
  if (/\d/.test(password)) points++;
  if (/[^A-Za-z0-9]/.test(password)) points++;
  // Long passwords made of one repeated character are not strong, whatever their length.
  if (new Set(password).size <= 2) points = 0;

  const score = (points <= 1 ? 2 : points === 2 ? 3 : 4) as 2 | 3 | 4;
  return { score, label: score === 2 ? "Fair" : score === 3 ? "Good" : "Strong", meetsMinimum };
}

import Link from "next/link";
import { Building2, LogIn } from "lucide-react";
import { AuthShell } from "@/components/auth/AuthShell";
import { Shimmer, authButtonClasses } from "@/components/auth/AuthButton";
import { BRAND } from "@/lib/brand";

export default function Home() {
  return (
    <AuthShell
      title={`Welcome to ${BRAND.productName}`}
      subtitle="Sign in to your workspace, or create a new organization to get started."
    >
      <div className="space-y-3">
        <Link href="/login" className={authButtonClasses("primary")}>
          <Shimmer />
          <span className="relative flex items-center gap-2">
            <LogIn size={16} aria-hidden /> Log in
          </span>
        </Link>
        <Link href="/signup" className={authButtonClasses("secondary")}>
          <Building2 size={16} aria-hidden /> Create an organization
        </Link>
      </div>
    </AuthShell>
  );
}

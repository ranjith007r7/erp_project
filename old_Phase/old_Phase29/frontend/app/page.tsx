import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4">
      <div className="max-w-md w-full text-center space-y-6">
        <h1 className="text-3xl font-bold text-slate-800 dark:text-white">Base ERP</h1>
        <p className="text-slate-500 dark:text-zinc-400">
          Customizable ERP platform — Core/Platform layer (Phase 1)
        </p>
        <div className="flex gap-4 justify-center">
          <Link
            href="/signup"
            className="px-5 py-2 rounded-lg bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 font-medium hover:bg-slate-700 dark:hover:bg-zinc-300 transition-colors"
          >
            Create Organization
          </Link>
          <Link
            href="/login"
            className="px-5 py-2 rounded-lg border border-slate-300 dark:border-zinc-700 text-slate-700 dark:text-zinc-200 font-medium hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors"
          >
            Log In
          </Link>
        </div>
      </div>
    </main>
  );
}

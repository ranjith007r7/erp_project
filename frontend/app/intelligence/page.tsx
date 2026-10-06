"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest, getToken } from "@/lib/api";
import { PageHeader, Card, Button } from "@/components/ui";
import { Sparkles, TriangleAlert, Info, Database, ChevronDown } from "lucide-react";

type Cell = string | number | boolean | null;

type AskResult = {
  answered: boolean;
  stage: string;
  answer: string;
  resolved_question: string;
  sql: string | null;
  columns: string[];
  rows: Cell[][];
  truncated: boolean;
  calls_used: number;
  detail: string | null;
  warning: string | null;
};

type Access = { is_admin: boolean; restricted: boolean; modules: string[] };
type Status = { llm_configured: boolean; database_configured: boolean; rows_sent_to_llm: boolean; model: string; access: Access };

type Turn = { id: number; question: string; result?: AskResult; error?: string };

// What each non-answer outcome means, in words a user can act on.
const STAGE_LABEL: Record<string, string> = {
  no_data: "No matching data",
  refused_scope: "Outside this data",
  blocked: "Could not build a safe query",
  db_error: "The query failed",
  llm_error: "AI unavailable",
  bad_input: "Check your question",
  denied: "You don't have access to that",
};

const HISTORY_EXCHANGES = 4; // matches the backend's default; the browser holds the conversation, the server stores none

function formatCell(value: Cell): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return String(value);
}

export default function IntelligencePage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [examples, setExamples] = useState<string[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [blocked, setBlocked] = useState<string | null>(null);
  // Suggested questions: open at first; collapses when one is clicked; always one tap away.
  const [suggestionsOpen, setSuggestionsOpen] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    apiRequest<Status>("/api/intelligence/status", { auth: true })
      .then(setStatus)
      .catch((e) => setBlocked(e instanceof Error ? e.message : "Could not load"));
    apiRequest<{ examples: string[] }>("/api/intelligence/manifest", { auth: true })
      .then((m) => setExamples(m.examples))
      .catch(() => {});
  }, [router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, loading]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || loading) return;
    const id = nextId.current++;
    // Only questions that were actually answered are useful context for a follow-up.
    const history = turns
      .filter((t) => t.result?.answered)
      .slice(-HISTORY_EXCHANGES)
      .map((t) => ({ question: t.question, answer: t.result!.answer }));

    setTurns((prev) => [...prev, { id, question: q }]);
    setQuestion("");
    setLoading(true);
    try {
      const result = await apiRequest<AskResult>("/api/intelligence/ask", {
        method: "POST",
        auth: true,
        body: { question: q, history },
      });
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, result } : t)));
    } catch (e) {
      const message = e instanceof Error ? e.message : "Something went wrong";
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, error: message } : t)));
    } finally {
      setLoading(false);
    }
  }

  const notReady = status && (!status.llm_configured || !status.database_configured);

  // Clears this tab's conversation (the only place it is kept). Nothing is stored on the server.
  function newChat() {
    setTurns([]);
    setQuestion("");
    setSuggestionsOpen(true);
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Ask your data" description="Ask questions in plain English. Answers come from your organization's own records, and the query behind every answer is shown." />

      {blocked && (
        <Card className="p-4 mb-4 max-w-3xl">
          <p className="text-sm text-red-600 dark:text-red-400">{blocked}</p>
        </Card>
      )}

      {status && (
        <div className="max-w-3xl mb-4 flex items-start gap-2 text-xs rounded-lg px-3 py-2 bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-900">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            {status.rows_sent_to_llm
              ? "Results are summarised by Google Gemini on its free tier. Google may use free-tier content to improve its models, so use demo or non-sensitive data only."
              : "Result rows are never sent to the AI. You get the verified table only."}{" "}
            This assistant can only read data; it can never change anything.
          </span>
        </div>
      )}

      {status && (
        <div className="max-w-3xl mb-4 text-xs text-slate-600 dark:text-zinc-400 space-y-1" data-testid="access-summary">
          {status.access.is_admin ? (
            <p>You can ask about everything, including salary and payroll.</p>
          ) : status.access.modules.length > 0 ? (
            <p>
              You can ask about: <span className="font-medium text-slate-800 dark:text-zinc-200">{status.access.modules.join(", ")}</span>.
            </p>
          ) : (
            <p>Your role has no data modules yet. Ask an administrator to give your role access to a module.</p>
          )}
          {!status.access.is_admin && !status.access.restricted && (
            <p>Salary and payroll questions are locked. They need the &quot;approve&quot; permission on Ask Data (and HR access).</p>
          )}
        </div>
      )}

      {notReady && (
        <Card className="p-4 mb-4 max-w-3xl">
          <p className="text-sm text-slate-700 dark:text-zinc-300 flex items-center gap-2">
            <Database size={16} /> Not set up yet:{" "}
            {!status!.llm_configured && "add GEMINI_API_KEY. "}
            {!status!.database_configured && "add UIL_DATABASE_URL (run scripts/setup_uil_role.py)."}
          </p>
        </Card>
      )}

      <div className="max-w-3xl space-y-4">
        {turns.map((t) => (
          <div key={t.id} className="space-y-2">
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-sm px-4 py-2 text-sm bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900">
                {t.question}
              </div>
            </div>
            <AnswerCard turn={t} />
          </div>
        ))}

        {loading && (
          <Card className="p-4">
            <div className="animate-pulse space-y-2">
              <div className="h-3 w-2/3 rounded bg-slate-200 dark:bg-zinc-800" />
              <div className="h-3 w-1/2 rounded bg-slate-200 dark:bg-zinc-800" />
            </div>
          </Card>
        )}
        <div ref={bottomRef} />
      </div>

      {examples.length > 0 && (
        <div className="max-w-3xl mt-6" data-testid="suggestions">
          <button
            type="button"
            onClick={() => setSuggestionsOpen((open) => !open)}
            aria-expanded={suggestionsOpen}
            aria-controls="suggested-questions"
            className="flex items-center gap-1.5 text-sm font-medium text-slate-600 dark:text-zinc-300 hover:text-slate-800 dark:hover:text-white transition-colors"
          >
            <Sparkles size={16} /> Suggested questions
            <ChevronDown size={16} className={`transition-transform ${suggestionsOpen ? "rotate-180" : ""}`} />
          </button>
          {suggestionsOpen && (
            <div id="suggested-questions" className="mt-2 flex flex-wrap gap-2">
              {examples.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => {
                    setSuggestionsOpen(false); // collapse after picking one; the bar above re-opens it
                    ask(ex);
                  }}
                  disabled={loading || !!notReady}
                  className="text-xs text-left rounded-full px-3 py-1.5 bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 hover:bg-slate-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors"
                >
                  {ex}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <form
        className="max-w-3xl mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <input
          type="text"
          value={question}
          maxLength={500}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Which invoices are overdue?"
          aria-label="Your question"
          disabled={!!notReady}
          className="flex-1 rounded-lg px-3 py-2 text-sm border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-slate-800 dark:text-white placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-slate-400 dark:focus:ring-zinc-600 disabled:opacity-50"
        />
        <Button type="submit" disabled={loading || !question.trim() || !!notReady}>
          {loading ? "Thinking…" : "Ask"}
        </Button>
      </form>

      <div className="max-w-3xl mt-2 flex items-start justify-between gap-4">
        <p className="text-xs text-slate-500 dark:text-zinc-500" data-testid="memory-note">
          This chat remembers the last few questions within the current session only, so follow-ups work naturally.
          Nothing is saved once this page is closed or refreshed. The memory exists only for as long as this tab stays open.
        </p>
        {turns.length > 0 && (
          <button
            type="button"
            onClick={newChat}
            disabled={loading}
            className="shrink-0 text-xs text-slate-600 dark:text-zinc-300 underline hover:text-slate-800 dark:hover:text-white disabled:opacity-50"
          >
            New chat
          </button>
        )}
      </div>
    </main>
  );
}

function AnswerCard({ turn }: { turn: Turn }) {
  const r = turn.result;
  if (turn.error) {
    return (
      <Card className="p-4">
        <p className="text-sm text-red-600 dark:text-red-400">{turn.error}</p>
      </Card>
    );
  }
  if (!r) return null;

  return (
    <Card className="p-4 space-y-3">
      {!r.answered && (
        <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400">
          <TriangleAlert size={14} /> {STAGE_LABEL[r.stage] ?? "Not answered"}
        </div>
      )}
      <p className="text-sm text-slate-800 dark:text-zinc-100 whitespace-pre-wrap">{r.answer}</p>

      {r.warning && (
        <p className="text-xs rounded-md px-2 py-1.5 bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300">{r.warning}</p>
      )}

      {r.columns.length > 0 && r.rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-zinc-800">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 dark:bg-zinc-800/60">
              <tr>
                {r.columns.map((c) => (
                  <th key={c} className="text-left font-medium px-3 py-2 text-slate-600 dark:text-zinc-300 whitespace-nowrap">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {r.rows.map((row, i) => (
                <tr key={i} className="border-t border-slate-100 dark:border-zinc-800">
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className={`px-3 py-1.5 whitespace-nowrap text-slate-800 dark:text-zinc-200 ${typeof cell === "number" ? "text-right tabular-nums" : ""}`}
                    >
                      {formatCell(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {r.truncated && <p className="text-xs text-slate-500 dark:text-zinc-500">Showing the first {r.rows.length} rows only.</p>}

      {r.sql && (
        <details className="text-xs">
          <summary className="cursor-pointer text-slate-500 dark:text-zinc-400 hover:text-slate-700 dark:hover:text-zinc-200">
            SQL used{r.detail && !r.answered ? " (rejected)" : ""}
          </summary>
          <pre className="mt-2 p-3 rounded-lg overflow-x-auto bg-slate-50 dark:bg-zinc-950 border border-slate-200 dark:border-zinc-800 text-slate-700 dark:text-zinc-300 whitespace-pre-wrap">
            {r.sql}
          </pre>
          {r.detail && !r.answered && <p className="mt-1 text-amber-700 dark:text-amber-400">Reason: {r.detail}</p>}
        </details>
      )}

      <p className="text-[11px] text-slate-400 dark:text-zinc-600">
        {r.calls_used} AI request{r.calls_used === 1 ? "" : "s"} used
        {r.resolved_question && r.resolved_question !== turn.question ? ` · understood as: ${r.resolved_question}` : ""}
      </p>
    </Card>
  );
}

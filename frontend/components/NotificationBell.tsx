"use client";

/**
 * A self-contained bell + dropdown. Polls unread-count every 30s so it
 * stays roughly current without needing websockets for a demo-scale app.
 * Deliberately dumb about WHERE it's placed — same reasoning as
 * CustomFieldsSection: drop it into any page's header with zero props
 * needed, and it works, because it reads the logged-in user from the
 * JWT the same way every other authenticated call does.
 */
import { useEffect, useRef, useState } from "react";
import { apiRequest } from "@/lib/api";

type Notification = {
  id: string;
  message: string;
  is_read: boolean;
  created_at: string;
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  function loadUnreadCount() {
    apiRequest<{ unread_count: number }>("/api/notifications/unread-count", { auth: true })
      .then((r) => setUnreadCount(r.unread_count))
      .catch(() => {});
  }

  useEffect(() => {
    loadUnreadCount();
    const interval = setInterval(loadUnreadCount, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function toggleOpen() {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      apiRequest<Notification[]>("/api/notifications", { auth: true })
        .then(setNotifications)
        .finally(() => setLoading(false));
    }
  }

  async function markAllRead() {
    await apiRequest("/api/notifications/read-all", { method: "POST", auth: true }).catch(() => {});
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    setUnreadCount(0);
  }

  async function markOneRead(id: string) {
    await apiRequest(`/api/notifications/${id}/read`, { method: "PATCH", auth: true }).catch(() => {});
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
    setUnreadCount((c) => Math.max(0, c - 1));
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={toggleOpen}
        className="relative text-slate-500 dark:text-zinc-500 hover:text-slate-700 dark:hover:text-zinc-300"
        aria-label="Notifications"
      >
        <span className="text-lg">🔔</span>
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-semibold rounded-full w-4 h-4 flex items-center justify-center">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 bg-white dark:bg-zinc-900 rounded-xl shadow-lg dark:shadow-none border border-slate-100 dark:border-zinc-800 z-50">
          <div className="flex justify-between items-center px-4 py-3 border-b border-slate-100 dark:border-zinc-800">
            <p className="text-sm font-semibold text-slate-700 dark:text-zinc-100">Notifications</p>
            {unreadCount > 0 && (
              <button onClick={markAllRead} className="text-xs text-slate-400 dark:text-zinc-500 hover:text-slate-600 dark:hover:text-zinc-300 underline">
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {loading && <p className="p-4 text-xs text-slate-400 dark:text-zinc-500">Loading…</p>}
            {!loading && notifications.length === 0 && (
              <p className="p-4 text-xs text-slate-400 dark:text-zinc-500">No notifications yet.</p>
            )}
            {!loading &&
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => !n.is_read && markOneRead(n.id)}
                  className={`w-full text-left px-4 py-3 border-b border-slate-50 dark:border-zinc-800 last:border-0 hover:bg-slate-50 dark:hover:bg-zinc-800 ${
                    n.is_read ? "opacity-60" : ""
                  }`}
                >
                  <p className="text-sm text-slate-700 dark:text-zinc-100">{n.message}</p>
                  <p className="text-[11px] text-slate-400 dark:text-zinc-500 mt-0.5">
                    {new Date(n.created_at).toLocaleString()}
                  </p>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

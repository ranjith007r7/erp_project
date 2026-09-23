"use client";

import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { useTheme } from "@/components/ThemeProvider";

// A fixed, readable palette - distinct enough to tell apart at a glance
// across a handful of slices (a lead/opportunity/PO/project status list
// is never more than 5-6 categories in practice), with genuinely
// different light/dark variants rather than the same hex reused, since
// mid-tone colors that read fine on white can wash out on black.
const PALETTE_LIGHT = ["#1e293b", "#0ea5e9", "#f59e0b", "#10b981", "#f43f5e", "#8b5cf6"];
const PALETTE_DARK = ["#e4e4e7", "#38bdf8", "#fbbf24", "#34d399", "#fb7185", "#a78bfa"];

export function BreakdownPieChart({ items }: { items: { label: string; value: number }[] }) {
  const { theme } = useTheme();
  const palette = theme === "dark" ? PALETTE_DARK : PALETTE_LIGHT;
  const textColor = theme === "dark" ? "#a1a1aa" : "#64748b";
  const tooltipBg = theme === "dark" ? "#18181b" : "#ffffff";
  const tooltipBorder = theme === "dark" ? "#3f3f46" : "#e2e8f0";

  const filtered = (items || []).filter((i) => i.value > 0);
  if (filtered.length === 0) {
    return <p className="text-sm text-slate-400 dark:text-zinc-500 p-4">No data yet.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={filtered}
          dataKey="value"
          nameKey="label"
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={80}
          paddingAngle={2}
        >
          {filtered.map((_, i) => (
            <Cell key={i} fill={palette[i % palette.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{ backgroundColor: tooltipBg, border: `1px solid ${tooltipBorder}`, borderRadius: 8, fontSize: 13 }}
          formatter={(value: number, name: string) => [value.toLocaleString("en-IN"), name]}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: textColor }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

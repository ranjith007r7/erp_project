"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useTheme } from "@/components/ThemeProvider";

export function IncomeBars({ data }: { data: { label: string; amount: number }[] }) {
  const { theme } = useTheme();
  const grid = theme === "dark" ? "#3f3f46" : "#e2e8f0";
  const text = theme === "dark" ? "#a1a1aa" : "#64748b";
  const bar = theme === "dark" ? "#818cf8" : "#4f46e5";
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: text, fontSize: 12 }} axisLine={{ stroke: grid }} tickLine={false} />
        <YAxis tick={{ fill: text, fontSize: 12 }} axisLine={false} tickLine={false} width={56} tickFormatter={(v) => Number(v).toLocaleString("en-IN")} />
        <Tooltip
          cursor={{ fill: theme === "dark" ? "#27272a" : "#f1f5f9" }}
          contentStyle={{ backgroundColor: theme === "dark" ? "#18181b" : "#fff", border: `1px solid ${grid}`, borderRadius: 8, fontSize: 13 }}
          formatter={(v: number) => [`₹${v.toLocaleString("en-IN")}`, "Income"]}
        />
        <Bar dataKey="amount" fill={bar} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

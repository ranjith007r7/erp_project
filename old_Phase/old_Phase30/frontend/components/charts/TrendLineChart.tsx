"use client";

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { useTheme } from "@/components/ThemeProvider";

/**
 * Recharts renders as inline-styled SVG, not HTML with Tailwind classes -
 * it never picks up dark: variants automatically the way the rest of this
 * app's components do. Every color here is passed explicitly, keyed off
 * the same useTheme() hook the rest of the app already uses, so a chart
 * genuinely matches whichever theme is active rather than rendering with
 * light-mode colors on a dark page (or vice versa).
 */
type Series = { key: string; label: string; color: { light: string; dark: string } };

export function TrendLineChart({
  data,
  xKey,
  series,
  valuePrefix = "",
}: {
  data: Record<string, string | number>[];
  xKey: string;
  series: Series[];
  valuePrefix?: string;
}) {
  const { theme } = useTheme();
  const gridColor = theme === "dark" ? "#3f3f46" : "#e2e8f0"; // zinc-700 / slate-200
  const textColor = theme === "dark" ? "#a1a1aa" : "#64748b"; // zinc-400 / slate-500
  const tooltipBg = theme === "dark" ? "#18181b" : "#ffffff"; // zinc-900 / white
  const tooltipBorder = theme === "dark" ? "#3f3f46" : "#e2e8f0";

  if (!data || data.length === 0) {
    return <p className="text-sm text-slate-400 dark:text-zinc-500 p-4">No data yet.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
        <XAxis dataKey={xKey} tick={{ fill: textColor, fontSize: 12 }} axisLine={{ stroke: gridColor }} tickLine={false} />
        <YAxis
          tick={{ fill: textColor, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${valuePrefix}${Number(v).toLocaleString("en-IN")}`}
          width={valuePrefix ? 70 : 40}
        />
        <Tooltip
          contentStyle={{ backgroundColor: tooltipBg, border: `1px solid ${tooltipBorder}`, borderRadius: 8, fontSize: 13 }}
          labelStyle={{ color: textColor }}
          formatter={(value: number) => [`${valuePrefix}${value.toLocaleString("en-IN")}`, undefined]}
        />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: textColor }} />}
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={theme === "dark" ? s.color.dark : s.color.light}
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

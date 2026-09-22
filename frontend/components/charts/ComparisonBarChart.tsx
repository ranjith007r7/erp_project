"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { useTheme } from "@/components/ThemeProvider";

/**
 * Horizontal layout deliberately chosen over vertical bars - category
 * labels (vendor names, product names, department names) are often too
 * long to read rotated or squeezed under vertical bars; horizontal bars
 * give labels their own full-width row on the left, same reasoning that
 * made the original hand-rolled BarList component use horizontal bars.
 */
export function ComparisonBarChart({
  items,
  valuePrefix = "",
  barColor,
}: {
  items: { label: string; value: number }[];
  valuePrefix?: string;
  barColor?: { light: string; dark: string };
}) {
  const { theme } = useTheme();
  const gridColor = theme === "dark" ? "#3f3f46" : "#e2e8f0";
  const textColor = theme === "dark" ? "#a1a1aa" : "#64748b";
  const tooltipBg = theme === "dark" ? "#18181b" : "#ffffff";
  const tooltipBorder = theme === "dark" ? "#3f3f46" : "#e2e8f0";
  // Matches the app's established primary-action color: slate-800 in
  // light mode, inverted to zinc-200 in dark mode - same convention
  // used for every primary button in the app.
  const defaultColor = theme === "dark" ? "#e4e4e7" : "#1e293b";
  const fill = barColor ? (theme === "dark" ? barColor.dark : barColor.light) : defaultColor;

  if (!items || items.length === 0) {
    return <p className="text-sm text-slate-400 dark:text-zinc-500 p-4">No data yet.</p>;
  }

  const height = Math.max(120, items.length * 36 + 20);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={items} layout="vertical" margin={{ top: 4, right: 24, left: 4, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} horizontal={false} />
        <XAxis
          type="number"
          tick={{ fill: textColor, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${valuePrefix}${Number(v).toLocaleString("en-IN")}`}
        />
        <YAxis
          type="category"
          dataKey="label"
          tick={{ fill: textColor, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={110}
        />
        <Tooltip
          contentStyle={{ backgroundColor: tooltipBg, border: `1px solid ${tooltipBorder}`, borderRadius: 8, fontSize: 13 }}
          cursor={{ fill: theme === "dark" ? "#27272a" : "#f1f5f9" }}
          formatter={(value: number) => [`${valuePrefix}${value.toLocaleString("en-IN")}`, undefined]}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
          {items.map((_, i) => (
            <Cell key={i} fill={fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

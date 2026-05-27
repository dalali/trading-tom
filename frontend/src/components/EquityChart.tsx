/**
 * EquityChart — Recharts AreaChart with accent gradient fill.
 * Wraps Recharts so the library can be swapped without touching call sites.
 */
import React from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { formatMoney } from "./Money";

interface DataPoint {
  ts: string;
  equity_cents: number;
}

interface EquityChartProps {
  data: DataPoint[];
  height?: number;
}

function formatDate(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
}

function formatYAxis(cents: number): string {
  if (cents >= 1_000_000) return `$${(cents / 100_000).toFixed(0)}k`;
  const d = cents / 100;
  return `$${(d / 1000).toFixed(1)}k`;
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--bg-surface)",
      border: "1px solid var(--border-subtle)",
      borderRadius: 8,
      padding: "10px 14px",
      fontSize: 13,
    }}>
      <div style={{ color: "var(--text-muted)", marginBottom: 4 }}>{label}</div>
      <div className="mono" style={{ color: "var(--text-primary)", fontWeight: 600 }}>
        {formatMoney(payload[0].value)} equity
      </div>
    </div>
  );
}

export function EquityChart({ data, height = 220 }: EquityChartProps) {
  if (!data.length) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
        No equity data yet
      </div>
    );
  }

  const chartData = data.map((d) => ({
    date: formatDate(d.ts),
    equity: d.equity_cents,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--accent)" stopOpacity={0.3} />
            <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} opacity={0.3} />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--text-muted)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tickFormatter={formatYAxis}
          tick={{ fill: "var(--text-muted)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={60}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="var(--accent)"
          strokeWidth={2}
          fill="url(#equityGradient)"
          dot={false}
          activeDot={{ r: 4, fill: "var(--accent)" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

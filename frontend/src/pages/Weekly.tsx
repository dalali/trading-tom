/**
 * Weekly Dashboard — equity chart, summary strip, daily breakdown.
 * E1–E2, FR-26
 */
import React from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { useAccountScope } from "../context/AccountScope";
import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";
import { StatCard } from "../components/StatCard";
import { Money, PnLValue } from "../components/Money";
import { EquityChart } from "../components/EquityChart";

export function Weekly() {
  const { accountId } = useAccountScope();
  const { data: weekly, loading: wLoading } = usePolling(
    () => accountId ? api.getWeekly(accountId) : Promise.reject("no account"),
    { enabled: accountId !== null, interval: 30_000 }
  );
  const { data: equity } = usePolling(
    () => accountId ? api.getEquity(accountId, "week") : Promise.reject("no account"),
    { enabled: accountId !== null, interval: 30_000 }
  );

  if (!accountId) return <div style={{ color: "var(--text-muted)", padding: 40 }}>No account selected.</div>;
  if (wLoading) return <div style={{ color: "var(--text-muted)" }}>Loading...</div>;
  if (!weekly) return null;

  return (
    <div style={{ maxWidth: "var(--max-content)" }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600 }}>Weekly</h1>
        <span style={{ color: "var(--text-muted)", fontSize: 14 }}>
          {weekly.week_start} — {weekly.week_end}
        </span>
      </div>

      {/* Equity chart */}
      <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", padding: "var(--space-6)", marginBottom: 24 }}>
        <div style={{ marginBottom: 12, display: "flex", alignItems: "baseline", gap: 12 }}>
          <span style={{ fontWeight: 600, fontSize: 15 }}>Equity This Week</span>
          <PnLValue cents={weekly.net_pnl_cents} />
        </div>
        <EquityChart data={equity ?? []} height={200} />
      </div>

      {/* Summary cards */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 24 }}>
        <StatCard label="Total Trades" value={weekly.total_trades} />
        <StatCard
          label="Win Rate"
          value={`${(weekly.win_rate * 100).toFixed(1)}%`}
        />
        <StatCard label="Net P&L" value={<PnLValue cents={weekly.net_pnl_cents} />} />
        <StatCard label="Total Fees" value={<Money cents={weekly.fees_cents} />} />
        <StatCard
          label="Avg Win / Loss"
          value={
            <span>
              <span style={{ color: "var(--profit)", fontFamily: "JetBrains Mono, monospace", fontSize: 18 }}>
                +${(weekly.avg_win_cents / 100).toFixed(0)}
              </span>
              <span style={{ color: "var(--text-muted)", fontSize: 14 }}> / </span>
              <span style={{ color: "var(--loss)", fontFamily: "JetBrains Mono, monospace", fontSize: 18 }}>
                -${(Math.abs(weekly.avg_loss_cents) / 100).toFixed(0)}
              </span>
            </span>
          }
        />
      </div>

      {/* Daily breakdown table */}
      <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", overflow: "hidden" }}>
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", fontWeight: 600, fontSize: 13 }}>
          Daily Breakdown
        </div>
        {weekly.daily_breakdown.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>No activity this week.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--bg-surface-2)" }}>
                {["Day", "Trades", "Win %", "Net P&L", "Fees"].map((h) => (
                  <th key={h} style={{ padding: "8px 16px", textAlign: "left", fontSize: 11, color: "var(--text-muted)", fontWeight: 500, textTransform: "uppercase" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {weekly.daily_breakdown.map((day) => (
                <tr key={day.date}>
                  <td style={{ padding: "10px 16px" }}>{new Date(day.date).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</td>
                  <td style={{ padding: "10px 16px" }} className="mono">{day.trade_count}</td>
                  <td style={{ padding: "10px 16px" }} className="mono">{(day.win_pct * 100).toFixed(0)}%</td>
                  <td style={{ padding: "10px 16px" }}><PnLValue cents={day.net_pnl_cents} /></td>
                  <td style={{ padding: "10px 16px" }}><Money cents={day.fees_cents} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

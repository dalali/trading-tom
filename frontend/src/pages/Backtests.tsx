/**
 * Backtests — list backtest runs with metrics and split provenance.
 */
import React from "react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";
import { Badge } from "../components/Badge";
import { Money, PnLValue } from "../components/Money";

export function Backtests() {
  const { data: runs, loading } = usePolling(
    () => api.listStrategies().then(() => fetch("/api/backtests?page_size=50").then(r => r.json())),
    { interval: 60_000 }
  );

  if (loading) return <div style={{ color: "var(--text-muted)" }}>Loading backtests...</div>;

  const items: any[] = Array.isArray(runs) ? runs : [];

  return (
    <div style={{ maxWidth: "var(--max-content)" }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600 }}>Backtest Runs</h1>
      </div>

      {items.length === 0 ? (
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}>
          No backtest runs yet. Use the API to run a backtest.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {items.map((run: any) => (
            <div key={run.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", padding: "var(--space-6)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
                <span style={{ fontWeight: 600 }}>#{run.id} — {run.strategy_name}</span>
                <Badge label={run.data_split} variant="split" />
                {run.final_evaluation && <Badge label="FINAL EVAL" variant="bust" />}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12 }}>
                {[
                  ["Return", `${((run.metrics?.total_return ?? 0) * 100).toFixed(2)}%`],
                  ["Win Rate", `${((run.metrics?.win_rate ?? 0) * 100).toFixed(1)}%`],
                  ["Sharpe", (run.metrics?.sharpe ?? 0).toFixed(2)],
                  ["Max DD", `${((run.metrics?.max_drawdown ?? 0) * 100).toFixed(1)}%`],
                  ["Trades", run.metrics?.n_trades ?? 0],
                  ["Net P&L", `$${((run.metrics?.net_pnl_cents ?? 0) / 100).toFixed(2)}`],
                ].map(([label, val]) => (
                  <div key={label as string} style={{ background: "var(--bg-surface-2)", borderRadius: 6, padding: "8px 12px" }}>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4, textTransform: "uppercase" }}>{label}</div>
                    <div className="mono" style={{ fontSize: 14, fontWeight: 600 }}>{val}</div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 12, fontSize: 12, color: "var(--text-muted)" }}>
                {run.period_start?.slice(0, 10)} → {run.period_end?.slice(0, 10)} · {run.symbols?.join(", ")} · Created {new Date(run.created_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

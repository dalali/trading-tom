/**
 * Daily Dashboard — today's trades, running balance, fees, open positions.
 * D1–D3, FR-25
 */
import React from "react";
import { useAccountScope } from "../context/AccountScope";
import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";
import { StatCard } from "../components/StatCard";
import { Money, PnLValue } from "../components/Money";
import { TradeRow, TRADE_COLUMNS } from "../components/TradeRow";
import { Badge } from "../components/Badge";

function PositionsTable({ positions }: { positions: ReturnType<typeof api.getPositions> extends Promise<infer T> ? T : any[] }) {
  if (!positions.length) return null;
  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", overflow: "hidden", marginBottom: 24 }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", fontWeight: 600, fontSize: 13 }}>
        Open Positions ({positions.length})
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "var(--bg-surface-2)" }}>
              {["Symbol", "Qty", "Avg Entry", "Latest", "Mkt Value", "Unrealized P&L"].map((h) => (
                <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, color: "var(--text-muted)", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => (
              <tr key={pos.id}>
                <td style={{ padding: "10px 12px", fontWeight: 600 }}>{pos.symbol}</td>
                <td style={{ padding: "10px 12px" }} className="mono">{pos.quantity}</td>
                <td style={{ padding: "10px 12px" }}><Money cents={pos.avg_entry_price_cents} /></td>
                <td style={{ padding: "10px 12px" }}>
                  {pos.latest_price_cents != null ? <Money cents={pos.latest_price_cents} /> : "—"}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  {pos.market_value_cents != null ? <Money cents={pos.market_value_cents} /> : "—"}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  {pos.unrealized_pnl_cents != null ? <PnLValue cents={pos.unrealized_pnl_cents} /> : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Daily() {
  const { accountId } = useAccountScope();
  const { data, loading, error } = usePolling(
    () => accountId ? api.getDaily(accountId) : Promise.reject("No account"),
    { enabled: accountId !== null, interval: 30_000 }
  );

  if (!accountId) return <div style={{ color: "var(--text-muted)", padding: 40 }}>No account selected. Start the engine in Settings.</div>;
  if (loading) return <div style={{ color: "var(--text-muted)" }}>Loading...</div>;
  if (error) return <div style={{ color: "var(--loss)" }}>Error loading daily data: {error.message}</div>;
  if (!data) return null;

  const today = new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric", timeZone: "America/New_York" });

  return (
    <div style={{ maxWidth: "var(--max-content)" }}>
      <div style={{ marginBottom: 24, display: "flex", alignItems: "baseline", gap: 12 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600 }}>Daily</h1>
        <span style={{ color: "var(--text-muted)", fontSize: 14 }}>{today}</span>
      </div>

      {/* Hero stat cards */}
      <div style={{ display: "flex", gap: 16, marginBottom: 24, flexWrap: "wrap" }}>
        <StatCard
          label="Equity"
          value={<Money cents={data.equity_cents} />}
          sub={`Cash: ${(data.cash_cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" })}`}
        />
        <StatCard
          label="Today Net P&L"
          value={<PnLValue cents={data.net_pnl_cents} />}
          sub={data.trade_count > 0 ? `${data.trade_count} trade${data.trade_count !== 1 ? "s" : ""}` : "No trades today"}
        />
        <StatCard
          label="Fees Today"
          value={<Money cents={data.fees_cents} />}
          sub={`${data.trades.filter(t => t.side === "sell").length} sells`}
        />
      </div>

      {/* Open positions */}
      <PositionsTable positions={data.open_positions} />

      {/* Trades table */}
      <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", overflow: "hidden" }}>
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", fontWeight: 600, fontSize: 13 }}>
          Today's Trades ({data.trade_count})
        </div>
        {data.trades.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
            No trades today — market closed or engine idle.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "var(--bg-surface-2)" }}>
                  {TRADE_COLUMNS.map((h) => (
                    <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, color: "var(--text-muted)", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.trades.map((t) => <TradeRow key={t.id} trade={t} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

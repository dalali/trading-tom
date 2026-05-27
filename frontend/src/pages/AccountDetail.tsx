/**
 * Account Detail — full trade history + lifetime summary + equity curve.
 * F2, FR-28
 */
import React, { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";
import { Money, PnLValue } from "../components/Money";
import { Badge } from "../components/Badge";
import { StatCard } from "../components/StatCard";
import { EquityChart } from "../components/EquityChart";
import { TradeRow, TRADE_COLUMNS } from "../components/TradeRow";
import { ChevronLeft } from "lucide-react";

export function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const accountId = Number(id);
  const [page, setPage] = useState(1);

  const { data: account } = usePolling(() => api.getAccount(accountId), { interval: 30_000 });
  const { data: equity } = usePolling(() => api.getEquity(accountId, "all"), { interval: 60_000 });
  const { data: trades } = usePolling(
    () => api.listTrades(accountId, page, 50),
    { interval: 30_000 }
  );

  if (!account) return <div style={{ color: "var(--text-muted)" }}>Loading account...</div>;

  const returnCents = account.cash_cents - account.starting_capital_cents;
  const returnPct = account.starting_capital_cents
    ? (returnCents / account.starting_capital_cents) * 100
    : 0;

  return (
    <div style={{ maxWidth: "var(--max-content)" }}>
      <div style={{ marginBottom: 20, display: "flex", alignItems: "center", gap: 12 }}>
        <Link to="/accounts" style={{ color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: 4, textDecoration: "none", fontSize: 13 }}>
          <ChevronLeft size={16} /> Accounts
        </Link>
        <span style={{ color: "var(--text-muted)" }}>/</span>
        <h1 style={{ fontSize: 18, fontWeight: 600 }}>
          Account #{account.id}
          <Badge
            label={account.status.toUpperCase()}
            variant={account.status === "active" ? "active" : "archived"}
            className="ml-2"
          />
        </h1>
      </div>

      {account.closed_at && (
        <div style={{ background: "rgba(240,185,11,0.1)", border: "1px solid rgba(240,185,11,0.3)", borderRadius: 8, padding: "8px 16px", marginBottom: 16, fontSize: 13, color: "var(--warning)" }}>
          Viewing archived account #{account.id} — closed {new Date(account.closed_at).toLocaleDateString("en-US", { timeZone: "America/New_York" })}
        </div>
      )}

      {/* Lifetime summary */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 24 }}>
        <StatCard label="Starting Capital" value={<Money cents={account.starting_capital_cents} />} />
        <StatCard label="Current Balance" value={<Money cents={account.cash_cents} />} />
        <StatCard
          label="Total Return"
          value={
            <span className="mono" style={{ color: returnCents >= 0 ? "var(--profit)" : "var(--loss)" }}>
              {returnCents >= 0 ? "+" : ""}{returnPct.toFixed(2)}%
            </span>
          }
        />
        <StatCard label="Win Rate" value={`${(account.win_rate * 100).toFixed(1)}%`} />
        <StatCard label="Total Trades" value={account.trade_count} />
        <StatCard label="Total Fees" value={<Money cents={account.total_fees_cents} />} />
      </div>

      {/* Equity chart */}
      <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", padding: "var(--space-6)", marginBottom: 24 }}>
        <div style={{ marginBottom: 12, fontWeight: 600, fontSize: 15 }}>Lifetime Equity Curve</div>
        <EquityChart data={equity ?? []} height={200} />
      </div>

      {/* Trade history */}
      <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", overflow: "hidden" }}>
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Trade History ({trades?.total ?? 0})</span>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              disabled={page === 1}
              onClick={() => setPage(p => Math.max(1, p - 1))}
              style={{ background: "var(--bg-surface-2)", border: "1px solid var(--border-subtle)", borderRadius: 6, padding: "4px 10px", cursor: "pointer", color: "var(--text-secondary)", fontSize: 12 }}
            >
              Prev
            </button>
            <span style={{ fontSize: 12, color: "var(--text-muted)", alignSelf: "center" }}>Page {page}</span>
            <button
              disabled={!trades || trades.trades.length < 50}
              onClick={() => setPage(p => p + 1)}
              style={{ background: "var(--bg-surface-2)", border: "1px solid var(--border-subtle)", borderRadius: 6, padding: "4px 10px", cursor: "pointer", color: "var(--text-secondary)", fontSize: 12 }}
            >
              Next
            </button>
          </div>
        </div>
        {!trades || trades.trades.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>No trades yet.</div>
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
                {trades.trades.map((t) => <TradeRow key={t.id} trade={t} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

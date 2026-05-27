/**
 * Accounts — list all accounts (active + archived), account switcher.
 * F1, F3, FR-27
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { useAccountScope } from "../context/AccountScope";
import { Money, PnLValue } from "../components/Money";
import { Badge, StatusDot } from "../components/Badge";
import { Account } from "../api/client";

function AccountRow({ account, onSetScope }: { account: Account; onSetScope: (id: number) => void }) {
  const navigate = useNavigate();
  const isBust = account.status === "archived" && account.cash_cents === 0;
  const returnCents = account.cash_cents - account.starting_capital_cents;
  const returnPct = account.starting_capital_cents
    ? ((account.cash_cents - account.starting_capital_cents) / account.starting_capital_cents) * 100
    : 0;

  return (
    <tr
      style={{ cursor: "pointer" }}
      onClick={() => navigate(`/accounts/${account.id}`)}
    >
      <td style={{ padding: "12px 16px", fontWeight: 600 }}>#{account.id}</td>
      <td style={{ padding: "12px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {account.status === "active" && <StatusDot status="running" />}
          <Badge
            label={isBust ? "BUST" : account.status.toUpperCase()}
            variant={account.status === "active" ? "active" : isBust ? "bust" : "archived"}
          />
        </div>
      </td>
      <td style={{ padding: "12px 16px", color: "var(--text-muted)", fontSize: 12 }}>
        {new Date(account.created_at).toLocaleDateString("en-US", { timeZone: "America/New_York" })}
      </td>
      <td style={{ padding: "12px 16px", color: "var(--text-muted)", fontSize: 12 }}>
        {account.closed_at
          ? new Date(account.closed_at).toLocaleDateString("en-US", { timeZone: "America/New_York" })
          : "—"}
      </td>
      <td style={{ padding: "12px 16px" }}><Money cents={account.starting_capital_cents} /></td>
      <td style={{ padding: "12px 16px" }}><Money cents={account.cash_cents} /></td>
      <td style={{ padding: "12px 16px" }}>
        <span className="mono" style={{ color: returnCents >= 0 ? "var(--profit)" : "var(--loss)" }}>
          {returnCents >= 0 ? "+" : ""}{returnPct.toFixed(2)}%
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>{account.trade_count}</td>
      <td style={{ padding: "12px 16px" }}>
        <button
          style={{
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-subtle)",
            borderRadius: 6,
            color: "var(--accent)",
            padding: "4px 10px",
            cursor: "pointer",
            fontSize: 12,
          }}
          onClick={(e) => {
            e.stopPropagation();
            onSetScope(account.id);
            navigate("/dashboard/daily");
          }}
        >
          View
        </button>
      </td>
    </tr>
  );
}

export function Accounts() {
  const { accounts, setAccountId, loading } = useAccountScope();

  if (loading) return <div style={{ color: "var(--text-muted)" }}>Loading accounts...</div>;

  return (
    <div style={{ maxWidth: "var(--max-content)" }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600 }}>Accounts ({accounts.length})</h1>
      </div>

      {accounts.length === 0 ? (
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}>
          No accounts yet — start the engine in Settings.
        </div>
      ) : (
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--bg-surface-2)" }}>
                {["#", "Status", "Opened", "Closed", "Start Capital", "Current Balance", "Return", "Trades", ""].map((h) => (
                  <th key={h} style={{ padding: "8px 16px", textAlign: "left", fontSize: 11, color: "var(--text-muted)", fontWeight: 500, textTransform: "uppercase" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <AccountRow key={a.id} account={a} onSetScope={setAccountId} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

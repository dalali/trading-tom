/**
 * TradeRow — a single row in the trades table.
 */
import React from "react";
import { Trade } from "../api/client";
import { Money, PnLValue } from "./Money";
import { Badge } from "./Badge";

interface TradeRowProps {
  trade: Trade;
}

function formatTime(ts: string): string {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/New_York",
    hour12: false,
  }) + " ET";
}

const TABLE_STYLE: React.CSSProperties = {
  display: "contents",
};

const CELL: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid var(--border-subtle)",
  fontSize: 13,
  verticalAlign: "middle",
};

export function TradeRow({ trade }: TradeRowProps) {
  const sideColor = trade.side === "buy" ? "var(--profit)" : "var(--loss)";
  return (
    <tr style={{ background: "transparent" }}>
      <td style={CELL} className="mono">{formatTime(trade.executed_at)}</td>
      <td style={{ ...CELL, fontWeight: 600 }}>{trade.symbol}</td>
      <td style={{ ...CELL, color: sideColor, textTransform: "uppercase", fontWeight: 600, fontSize: 12 }}>
        {trade.side}
      </td>
      <td style={{ ...CELL }} className="mono">{trade.quantity}</td>
      <td style={CELL}><Money cents={trade.price_cents} /></td>
      <td style={CELL} className="mono" style2={{ color: "var(--text-muted)" }}>
        <span style={{ color: "var(--text-muted)" }}>
          <Money cents={trade.fee_cents} />
        </span>
      </td>
      <td style={CELL}>
        {trade.realized_pnl_cents != null ? (
          <PnLValue cents={trade.realized_pnl_cents} />
        ) : (
          <span style={{ color: "var(--text-muted)" }}>—</span>
        )}
      </td>
      <td style={CELL}>
        <Badge label={trade.strategy_name} variant="strategy" />
      </td>
      <td style={CELL}>
        <Badge label={trade.data_split} variant="split" />
      </td>
    </tr>
  );
}

export const TRADE_COLUMNS = ["Time ET", "Symbol", "Side", "Qty", "Price", "Fee", "Realized P&L", "Strategy", "Split"];

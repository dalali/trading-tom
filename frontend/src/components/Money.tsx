/**
 * Money — formats integer cents → $X,XXX.XX
 * Optional sign coloring (profit/loss).
 */
import React from "react";

interface MoneyProps {
  cents: number;
  colored?: boolean;       // color by sign using --profit/--loss
  showSign?: boolean;      // force +/- prefix
  className?: string;
}

export function formatMoney(cents: number): string {
  const dollars = Math.abs(cents) / 100;
  return `$${dollars.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function Money({ cents, colored = false, showSign = false, className = "" }: MoneyProps) {
  const sign = cents > 0 ? "+" : cents < 0 ? "-" : "";
  const absFormatted = formatMoney(cents);
  const display = showSign || colored ? `${sign}${absFormatted}` : (cents < 0 ? `-${absFormatted}` : absFormatted);

  const color = colored
    ? cents > 0 ? "var(--profit)" : cents < 0 ? "var(--loss)" : "var(--text-secondary)"
    : undefined;

  return (
    <span
      className={`mono ${className}`}
      style={{ color }}
    >
      {display}
    </span>
  );
}

export function PnLValue({ cents, className = "" }: { cents: number; className?: string }) {
  const glyph = cents > 0 ? "▲" : cents < 0 ? "▼" : "";
  const color = cents > 0 ? "var(--profit)" : cents < 0 ? "var(--loss)" : "var(--text-secondary)";
  return (
    <span className={`mono ${className}`} style={{ color }}>
      {glyph}{formatMoney(Math.abs(cents))}
    </span>
  );
}

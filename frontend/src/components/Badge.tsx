/**
 * Badge / Pill — status, data-split, strategy tag, PAPER pill.
 */
import React from "react";

interface BadgeProps {
  label: string;
  variant?: "active" | "archived" | "paper" | "split" | "strategy" | "bust";
  className?: string;
}

const VARIANT_STYLES: Record<string, React.CSSProperties> = {
  active: { background: "rgba(76,141,255,0.15)", color: "var(--accent)", border: "1px solid var(--accent)" },
  archived: { background: "var(--bg-surface-2)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" },
  paper: { background: "var(--paper-pill-bg)", color: "var(--paper-pill-text)", border: "1px solid rgba(240,185,11,0.3)" },
  split: { background: "rgba(123,143,247,0.15)", color: "var(--info)", border: "1px solid var(--info)" },
  strategy: { background: "var(--bg-surface-2)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" },
  bust: { background: "rgba(234,57,67,0.15)", color: "var(--loss)", border: "1px solid var(--loss)" },
};

export function Badge({ label, variant = "strategy", className = "" }: BadgeProps) {
  const style: React.CSSProperties = {
    ...VARIANT_STYLES[variant],
    padding: "2px 8px",
    borderRadius: "var(--radius-pill)",
    fontSize: "11px",
    fontWeight: 500,
    fontFamily: "Inter, sans-serif",
    display: "inline-block",
    whiteSpace: "nowrap",
  };
  return <span style={style} className={className}>{label}</span>;
}

export function StatusDot({ status }: { status: "running" | "stopped" | "open" | "closed" }) {
  const color =
    status === "running" || status === "open"
      ? "var(--profit)"
      : "var(--text-muted)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        marginRight: 6,
        flexShrink: 0,
      }}
    />
  );
}

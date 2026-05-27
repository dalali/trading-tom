/**
 * StatCard — hero number + label + optional delta.
 */
import React, { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  sub?: string;
  className?: string;
}

export function StatCard({ label, value, delta, sub, className = "" }: StatCardProps) {
  return (
    <div
      className={className}
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-card)",
        padding: "var(--space-6)",
        flex: 1,
        minWidth: 0,
      }}
    >
      <div style={{ color: "var(--text-secondary)", fontSize: 12, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div style={{ fontSize: 32, fontWeight: 600, fontFamily: "JetBrains Mono, monospace", lineHeight: 1.2 }}>
        {value}
      </div>
      {delta && <div style={{ marginTop: 6, fontSize: 13 }}>{delta}</div>}
      {sub && <div style={{ marginTop: 4, color: "var(--text-muted)", fontSize: 12 }}>{sub}</div>}
    </div>
  );
}

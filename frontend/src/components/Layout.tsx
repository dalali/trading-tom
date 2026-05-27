/**
 * Layout — Sidebar + TopBar wrapper matching design.md §1.1.
 */
import React, { ReactNode, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  CalendarRange,
  Users,
  FlaskConical,
  Settings,
  TrendingUp,
} from "lucide-react";
import { Badge, StatusDot } from "./Badge";
import { useAccountScope } from "../context/AccountScope";
import { usePolling } from "../hooks/usePolling";
import { api, EngineStatus } from "../api/client";
import { Money } from "./Money";

const NAV_ITEMS = [
  { to: "/dashboard/daily", label: "Daily", icon: LayoutDashboard },
  { to: "/dashboard/weekly", label: "Weekly", icon: CalendarRange },
  { to: "/accounts", label: "Accounts", icon: Users },
  { to: "/backtests", label: "Backtests", icon: FlaskConical },
];

function Sidebar() {
  const { data: engineStatus } = usePolling(api.getEngineStatus, { interval: 15_000 });

  return (
    <aside
      style={{
        width: "var(--sidebar-width)",
        background: "var(--bg-surface)",
        borderRight: "1px solid var(--border-subtle)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        position: "fixed",
        left: 0,
        top: 0,
        zIndex: 10,
      }}
    >
      {/* Logo */}
      <div style={{ padding: "20px 20px 16px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <TrendingUp size={20} color="var(--accent)" />
          <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: "-0.02em" }}>Trading Tom</span>
          <Badge label="PAPER" variant="paper" />
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "12px 8px" }}>
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => ({
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 12px",
              borderRadius: 8,
              marginBottom: 2,
              color: isActive ? "var(--accent)" : "var(--text-secondary)",
              background: isActive ? "rgba(76,141,255,0.1)" : "transparent",
              textDecoration: "none",
              fontSize: 14,
              fontWeight: isActive ? 600 : 400,
              transition: "all 150ms ease",
            })}
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
        <div style={{ height: 1, background: "var(--border-subtle)", margin: "8px 4px" }} />
        <NavLink
          to="/settings"
          style={({ isActive }) => ({
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "8px 12px",
            borderRadius: 8,
            color: isActive ? "var(--accent)" : "var(--text-secondary)",
            background: isActive ? "rgba(76,141,255,0.1)" : "transparent",
            textDecoration: "none",
            fontSize: 14,
            fontWeight: isActive ? 600 : 400,
          })}
        >
          <Settings size={16} />
          Settings
        </NavLink>
      </nav>

      {/* Status footer */}
      <div style={{ padding: "12px 16px", borderTop: "1px solid var(--border-subtle)", fontSize: 12, color: "var(--text-secondary)" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
          <StatusDot status={engineStatus?.actual_state === "running" ? "running" : "stopped"} />
          Engine: {engineStatus?.actual_state?.toUpperCase() ?? "..."}
        </div>
        <div style={{ display: "flex", alignItems: "center" }}>
          <StatusDot status={engineStatus?.market_open ? "open" : "closed"} />
          Mkt: {engineStatus?.market_open ? "OPEN" : "CLOSED"} ET
        </div>
      </div>
    </aside>
  );
}

function TopBar() {
  const { accounts, accountId, setAccountId, activeAccount } = useAccountScope();
  const navigate = useNavigate();

  return (
    <header
      style={{
        position: "fixed",
        top: 0,
        left: "var(--sidebar-width)",
        right: 0,
        height: 56,
        background: "var(--bg-surface)",
        borderBottom: "1px solid var(--border-subtle)",
        display: "flex",
        alignItems: "center",
        padding: "0 24px",
        zIndex: 9,
        gap: 16,
      }}
    >
      {/* Account switcher */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Account:</span>
        <select
          value={accountId ?? ""}
          onChange={(e) => {
            const id = Number(e.target.value);
            setAccountId(id);
            navigate(`/accounts/${id}`);
          }}
          style={{
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-subtle)",
            borderRadius: 6,
            color: "var(--text-primary)",
            padding: "4px 8px",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              #{a.id} ({a.status === "active" ? "ACTIVE" : "ARCHIVED"}) — ${(a.cash_cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2 })}
            </option>
          ))}
        </select>
      </div>

      <div style={{ flex: 1 }} />

      {/* Current time ET */}
      <ClockET />
    </header>
  );
}

function ClockET() {
  const [time, setTime] = React.useState(new Date());
  React.useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const formatted = time.toLocaleString("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return <span style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "JetBrains Mono, monospace" }}>{formatted} ET</span>;
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar />
      <div style={{ marginLeft: "var(--sidebar-width)", flex: 1, display: "flex", flexDirection: "column" }}>
        <TopBar />
        <main style={{ marginTop: 56, flex: 1, padding: 24, overflowY: "auto" }}>
          {children}
        </main>
      </div>
    </div>
  );
}

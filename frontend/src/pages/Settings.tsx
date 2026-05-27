/**
 * Settings — engine control + strategy params.
 * B2, FR-13, FR-24
 */
import React, { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";
import { StatusDot } from "../components/Badge";

export function Settings() {
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const { data: engineStatus, refetch: refetchEngine } = usePolling(api.getEngineStatus, { interval: 10_000 });
  const { data: strategies, refetch: refetchStrategies } = usePolling(api.listStrategies, { interval: 30_000 });

  const toast = (text: string, ok: boolean) => {
    setMsg({ text, ok });
    setTimeout(() => setMsg(null), 3000);
  };

  const handleStart = async () => {
    try {
      await api.startEngine(token);
      toast("Engine started", true);
      refetchEngine();
    } catch {
      toast("Failed — check token", false);
    }
  };

  const handleStop = async () => {
    try {
      await api.stopEngine(token);
      toast("Engine stopped", true);
      refetchEngine();
    } catch {
      toast("Failed — check token", false);
    }
  };

  return (
    <div style={{ maxWidth: 800 }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 24 }}>Settings</h1>

      {msg && (
        <div style={{
          background: msg.ok ? "rgba(22,199,132,0.1)" : "rgba(234,57,67,0.1)",
          border: `1px solid ${msg.ok ? "var(--profit)" : "var(--loss)"}`,
          borderRadius: 8,
          padding: "10px 16px",
          marginBottom: 16,
          color: msg.ok ? "var(--profit)" : "var(--loss)",
          fontSize: 13,
        }}>
          {msg.text}
        </div>
      )}

      {/* Engine control */}
      <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", padding: "var(--space-6)", marginBottom: 20 }}>
        <div style={{ fontWeight: 600, marginBottom: 16 }}>Engine Control</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
          <StatusDot status={engineStatus?.actual_state === "running" ? "running" : "stopped"} />
          <span style={{ fontSize: 14 }}>
            Status: <strong>{engineStatus?.actual_state?.toUpperCase() ?? "..."}</strong>
          </span>
          {engineStatus?.last_tick_at && (
            <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
              — last tick {new Date(engineStatus.last_tick_at).toLocaleTimeString("en-US", { timeZone: "America/New_York" })} ET
            </span>
          )}
        </div>
        {engineStatus?.last_error && (
          <div style={{ background: "rgba(234,57,67,0.1)", border: "1px solid rgba(234,57,67,0.3)", borderRadius: 6, padding: "8px 12px", marginBottom: 12, fontSize: 12, color: "var(--loss)" }}>
            Last error: {engineStatus.last_error}
          </div>
        )}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="password"
            placeholder="Operator token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            style={{
              background: "var(--bg-surface-2)",
              border: "1px solid var(--border-subtle)",
              borderRadius: 6,
              color: "var(--text-primary)",
              padding: "6px 12px",
              fontSize: 13,
              width: 200,
            }}
          />
          <button
            onClick={handleStart}
            style={{ background: "var(--accent)", border: "none", borderRadius: 6, color: "#fff", padding: "6px 16px", cursor: "pointer", fontWeight: 600, fontSize: 13 }}
          >
            Start
          </button>
          <button
            onClick={handleStop}
            style={{ background: "rgba(234,57,67,0.1)", border: "1px solid var(--loss)", borderRadius: 6, color: "var(--loss)", padding: "6px 16px", cursor: "pointer", fontWeight: 600, fontSize: 13 }}
          >
            Stop
          </button>
        </div>
      </div>

      {/* Strategy params (read-only for MVP) */}
      <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-card)", padding: "var(--space-6)" }}>
        <div style={{ fontWeight: 600, marginBottom: 16 }}>Strategy Parameters</div>
        {!strategies ? (
          <div style={{ color: "var(--text-muted)" }}>Loading...</div>
        ) : (
          strategies.map((cfg) => (
            <div
              key={cfg.strategy_name}
              style={{
                marginBottom: 16,
                background: "var(--bg-surface-2)",
                borderRadius: 8,
                padding: "12px 16px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span style={{ fontWeight: 600, textTransform: "capitalize" }}>{cfg.strategy_name}</span>
                <span style={{
                  fontSize: 11,
                  padding: "2px 8px",
                  borderRadius: 999,
                  background: cfg.enabled ? "rgba(22,199,132,0.15)" : "rgba(92,103,115,0.2)",
                  color: cfg.enabled ? "var(--profit)" : "var(--text-muted)",
                }}>
                  {cfg.enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              <pre style={{ fontSize: 12, color: "var(--text-secondary)", margin: 0, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(cfg.params, null, 2)}
              </pre>
            </div>
          ))
        )}
        <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>
          Use the API (PUT /api/config/strategies/{"{name}"}) with an operator token to update params.
        </div>
      </div>
    </div>
  );
}

/**
 * Typed API client wrappers over the /api endpoints.
 * All money values arrive as integer cents.
 */
import axios from "axios";

const http = axios.create({ baseURL: "/api" });

// --- Types ---

export interface Account {
  id: number;
  status: "active" | "archived";
  created_at: string;
  closed_at: string | null;
  close_reason: string | null;
  starting_capital_cents: number;
  cash_cents: number;
  trade_count: number;
}

export interface AccountDetail extends Account {
  lifetime_return: number;
  win_rate: number;
  max_drawdown: number;
  sharpe: number;
  total_fees_cents: number;
  gross_pnl_cents: number;
}

export interface Position {
  id: number;
  symbol: string;
  quantity: number;
  avg_entry_price_cents: number;
  opened_at: string;
  unrealized_pnl_cents: number | null;
  market_value_cents: number | null;
  latest_price_cents: number | null;
}

export interface Trade {
  id: number;
  account_id: number;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price_cents: number;
  fee_cents: number;
  realized_pnl_cents: number | null;
  strategy_name: string;
  data_split: string;
  executed_at: string;
  backtest_run_id: number | null;
}

export interface TradeList {
  trades: Trade[];
  total: number;
  page: number;
  page_size: number;
}

export interface DailySummary {
  account_id: number;
  date: string;
  cash_cents: number;
  equity_cents: number;
  net_pnl_cents: number;
  fees_cents: number;
  trade_count: number;
  trades: Trade[];
  open_positions: Position[];
}

export interface DailyBreakdown {
  date: string;
  trade_count: number;
  win_pct: number;
  net_pnl_cents: number;
  fees_cents: number;
}

export interface WeeklySummary {
  account_id: number;
  week_start: string;
  week_end: string;
  total_trades: number;
  win_rate: number;
  gross_pnl_cents: number;
  net_pnl_cents: number;
  fees_cents: number;
  avg_win_cents: number;
  avg_loss_cents: number;
  daily_breakdown: DailyBreakdown[];
}

export interface EquityPoint {
  ts: string;
  equity_cents: number;
  cash_cents: number;
}

export interface EngineStatus {
  actual_state: string;
  desired_state: string;
  last_tick_at: string | null;
  last_error: string | null;
  market_open: boolean;
  updated_at: string;
}

export interface StrategyConfig {
  strategy_name: string;
  enabled: boolean;
  params: Record<string, unknown>;
  updated_at: string;
}

// --- API calls ---

export const api = {
  // Accounts
  listAccounts: () => http.get<Account[]>("/accounts").then((r) => r.data),
  getActiveAccount: () => http.get<Account>("/accounts/active").then((r) => r.data),
  getAccount: (id: number) => http.get<AccountDetail>(`/accounts/${id}`).then((r) => r.data),
  getPositions: (id: number) => http.get<Position[]>(`/accounts/${id}/positions`).then((r) => r.data),

  // Trades
  listTrades: (id: number, page = 1, page_size = 50) =>
    http.get<TradeList>(`/accounts/${id}/trades`, { params: { page, page_size } }).then((r) => r.data),

  // Dashboard
  getDaily: (id: number, date?: string) =>
    http.get<DailySummary>(`/accounts/${id}/daily`, { params: date ? { date } : {} }).then((r) => r.data),
  getWeekly: (id: number, week_start?: string) =>
    http.get<WeeklySummary>(`/accounts/${id}/weekly`, { params: week_start ? { week_start } : {} }).then((r) => r.data),
  getEquity: (id: number, range: "day" | "week" | "all" = "week") =>
    http.get<EquityPoint[]>(`/accounts/${id}/equity`, { params: { range } }).then((r) => r.data),

  // Engine
  getEngineStatus: () => http.get<EngineStatus>("/engine/status").then((r) => r.data),
  startEngine: (token: string) =>
    http.post("/engine/start", {}, { headers: { "X-Operator-Token": token } }).then((r) => r.data),
  stopEngine: (token: string) =>
    http.post("/engine/stop", {}, { headers: { "X-Operator-Token": token } }).then((r) => r.data),

  // Config
  listStrategies: () => http.get<StrategyConfig[]>("/config/strategies").then((r) => r.data),
  updateStrategy: (name: string, token: string, update: Partial<StrategyConfig>) =>
    http.put(`/config/strategies/${name}`, update, { headers: { "X-Operator-Token": token } }).then((r) => r.data),
};

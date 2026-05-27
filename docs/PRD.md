# Product Requirements Document — Trading Tom

**Version:** 1.0 (MVP)
**Status:** Draft for architecture
**Author:** Systems Analyst (PM pipeline)
**Date:** 2026-05-27

---

## 1. Overview

Trading Tom is a **paper-trading simulation bot** for US equities. It autonomously runs configurable trading strategies against real market data, executing **simulated-only** trades (no real money, no live broker order routing). It maintains virtual brokerage accounts that start with $10,000 of virtual capital, deduct realistic fees, and auto-recycle when an account is busted. A trading-platform-style dashboard lets the user review daily and weekly performance and browse the full history of every past account.

The product is for a single operator (the owner) who wants to develop, observe, and evaluate automated trading strategies in a realistic, risk-free environment. The defining engineering concern is **anti-overfitting**: strategies must be developed and evaluated using disciplined train/validation/test data separation so that observed performance is not an artifact of curve-fitting to known data.

### 1.1 Goals

1. Run 3+ pluggable trading strategies autonomously against US stock data.
2. Simulate realistic account lifecycle: capital, fees, P&L, bust-and-restart.
3. Provide a clean, trading-platform-grade dashboard for daily/weekly review and account history.
4. Enforce strict anti-overfitting data discipline (train/validation/test splits).
5. Deploy as an always-on service on a VPS via Docker Compose.

### 1.2 Non-Goals (see Section 8 for full out-of-scope list)

- Real-money trading or live broker integration.
- Multi-user accounts / authentication beyond a single operator.
- Mobile native apps.

---

## 2. Personas

| Persona | Description | Primary need |
|---------|-------------|--------------|
| **The Operator (Tom)** | Single owner running the bot on their VPS. Technically literate, interested in strategy performance. | See what the bot did, how each account is performing, and trust that results aren't overfit. |
| **The Bot (system actor)** | The autonomous trading engine. | Reliable market data, deterministic fee model, persistent account state. |

The MVP assumes a single trusted operator. There is no public/multi-tenant access in scope.

---

## 3. User Stories

### Epic A — Account Lifecycle
- **A1.** As the operator, each trading account starts with exactly $10,000 virtual capital so results are comparable across accounts.
- **A2.** As the operator, when an active account's balance falls to or below the configurable floor (default $0), the account is automatically closed and archived, and a new $10,000 account is opened, so trading continues uninterrupted.
- **A3.** As the operator, only one account is active at any time, so I always know which account the bot is currently trading.
- **A4.** As the operator, every closed account is archived with its full trade history so I can review past performance.

### Epic B — Trading Engine
- **B1.** As the operator, the bot autonomously selects and executes strategies based on market conditions during market hours, so I don't have to trigger trades manually.
- **B2.** As the operator, I can configure each strategy's parameters (e.g., thresholds, position sizing, watchlist), so I can tune behavior without code changes.
- **B3.** As the operator, every simulated trade deducts realistic estimated fees (regulatory fees for sells; configurable commission model), so reported P&L reflects real-world costs.
- **B4.** As the operator, the bot supports at least three strategy archetypes — day (intraday), swing (multi-day), and position (weeks/months) — so different holding-period behaviors can be observed.
- **B5.** As the operator, strategies are pluggable behind a common interface, so new strategies can be added without modifying the engine.

### Epic C — Anti-Overfitting Discipline
- **C1.** As the operator, historical data is partitioned into train / validation / test segments by date, and the test segment is never read during strategy development or parameter tuning, so reported results are not overfit.
- **C2.** As the operator, the system records which data split each backtest/run used, so I can audit that test data was held out.
- **C3.** As the operator, any parameter optimization runs only against train+validation data, and a single final evaluation runs against test data, so the test result is an honest out-of-sample estimate.

### Epic D — Dashboard: Daily View
- **D1.** As the operator, I can see all trades executed today (symbol, side, quantity, price, time), so I know what the bot did.
- **D2.** As the operator, I can see realized P&L per closed trade and unrealized P&L per open position today.
- **D3.** As the operator, I can see the running account balance and total fees paid today.

### Epic E — Dashboard: Weekly View
- **E1.** As the operator, I can see a weekly summary: total trades, win rate, gross P&L, total fees, net P&L.
- **E2.** As the operator, I can see a balance/equity chart over the week.

### Epic F — Dashboard: Account Switcher & History
- **F1.** As the operator, I can switch the dashboard to view any past (archived) account.
- **F2.** As the operator, for any account I can see its full trade history and lifetime performance summary.
- **F3.** As the operator, the active account is clearly distinguished from archived ones.

### Epic G — Look & Feel
- **G1.** As the operator, the dashboard looks and feels like a real trading platform (clean, chart-focused, dark-mode capable), drawing inspiration from Robinhood, eToro, Binance, and Exodus.

---

## 4. Functional Requirements

### 4.1 Account Management
- FR-1. The system maintains a persistent set of accounts. Exactly one has status `active`; all others are `archived`.
- FR-2. New accounts are created with `starting_capital` (default $10,000, configurable via env).
- FR-3. After each trade settles, the system checks the account's cash+equity value against `account_floor` (default $0, configurable). If at or below the floor, the account is marked `archived` (closed) with a close timestamp, and a new active account is created automatically.
- FR-4. Each account stores: id, status, created_at, closed_at (nullable), starting_capital, current cash balance, and a derived equity value (cash + market value of open positions).
- FR-5. Each account owns an ordered trade history and a set of positions.

### 4.2 Market Data
- FR-6. The system ingests historical and recent US stock OHLCV data from a free provider (Yahoo Finance via `yfinance` for MVP; Alpaca free tier as an optional alternative documented in architecture).
- FR-7. Market data is cached locally (database/disk) to avoid repeated external calls and to provide a stable dataset for backtests.
- FR-8. The system defines a configurable watchlist of US tickers the bot may trade.
- FR-9. "Live" paper trading operates on the most recent available data during US market hours (9:30–16:00 ET, Mon–Fri, excluding holidays). When the market is closed, the engine is idle (no new trades).

### 4.3 Trading Engine & Strategies
- FR-10. A `Strategy` interface exposes a method that, given current market context and account state, returns zero or more trade signals (buy/sell, symbol, quantity or sizing rule).
- FR-11. At minimum three strategies ship: `DayTradingStrategy` (intraday entries/exits, flat by close), `SwingTradingStrategy` (positions held days), `PositionTradingStrategy` (positions held weeks–months).
- FR-12. A strategy selector chooses which strategy/strategies are active based on simple, documented market-condition rules (e.g., volatility/trend regime). Selection logic must be deterministic and inspectable.
- FR-13. Strategy parameters are loaded from configuration (file and/or env), not hard-coded.
- FR-14. The engine executes signals as simulated orders at a realistic fill price (e.g., the relevant bar's close or next-bar open, documented in architecture), updates positions and cash, and records a trade.

### 4.4 Fee Model
- FR-15. A configurable fee model computes per-trade fees. Default: $0 commission; on sells, apply estimated US regulatory fees (SEC fee and FINRA TAF) using current published rates, configurable via env. The exact rate constants live in config so they can be updated.
- FR-16. Fees are deducted from account cash at trade time and recorded on the trade.

### 4.5 Anti-Overfitting
- FR-17. Historical data per symbol is partitioned by date into three contiguous segments: train, validation, test (default ratio 60/20/20, configurable, chronological — test is the most recent).
- FR-18. A "mode" flag governs data access: development/optimization code may read train and validation only; a separate, explicit "final evaluation" mode reads test. The data access layer enforces this — requesting test data outside final-evaluation mode raises an error.
- FR-19. Each backtest/evaluation run records which split(s) it used and stores this with results.

### 4.6 Backtesting & Live Paper Trading
- FR-20. The engine supports a backtest mode that replays a chosen historical split bar-by-bar against a strategy, producing trades, P&L, fees, and summary metrics (total return, win rate, max drawdown, Sharpe).
- FR-21. The engine supports a live paper-trading mode that runs on a schedule during market hours, advancing the active account.
- FR-22. Backtest results are persisted and viewable; live results feed the active account's history.

### 4.7 API (backend)
- FR-23. REST API exposes: list accounts; get account detail; get active account; list trades for an account (filterable by date/day/week); daily summary; weekly summary; list/get backtest runs; engine status/health.
- FR-24. The API is read-oriented for the dashboard; write operations (start engine, run backtest, change config) are operator-only control endpoints.

### 4.8 Dashboard (frontend)
- FR-25. Daily view: today's trades table, per-trade P&L, running balance, fees paid, open positions with unrealized P&L.
- FR-26. Weekly view: summary metrics (trades, win rate, gross/net P&L, fees) and an equity chart.
- FR-27. Account switcher: dropdown/list of accounts; selecting one re-scopes daily/weekly/history views; active account is badged.
- FR-28. Account history: full trade list and lifetime summary for the selected account.
- FR-29. Dark-mode-capable, chart-focused, trading-platform aesthetic.

---

## 5. Non-Functional Requirements

### 5.1 Performance
- NFR-1. Dashboard API responses for daily/weekly/account views return in < 500 ms for an account with up to ~10,000 trades.
- NFR-2. A backtest over one symbol-year of daily bars completes in < 30 s on a modest VPS (2 vCPU / 4 GB).
- NFR-3. The live engine tick (evaluate strategies + execute signals across the watchlist) completes well within its scheduling interval.

### 5.2 Anti-Overfitting / Scientific Integrity
- NFR-4. Test-segment data is inaccessible to development/optimization code paths by construction (enforced, not merely by convention).
- NFR-5. Every recorded run is traceable to the exact data split and strategy parameters used (reproducibility).
- NFR-6. Backtests are deterministic given the same data, parameters, and seed.

### 5.3 Data Integrity
- NFR-7. Account cash, positions, and trades are persisted transactionally so the ledger is always consistent (no partially-applied trades).
- NFR-8. Monetary values use a precise representation (integer cents or Decimal) — never binary floats for money.
- NFR-9. The account ledger is auditable: for any account, summing trades + fees reconciles to the recorded balance.

### 5.4 Reliability / Operability
- NFR-10. The system runs unattended on an always-on VPS; on restart it resumes from persisted state without data loss.
- NFR-11. `run.sh` provides start/stop/restart/logs/build/status/test/shell/clean/help.
- NFR-12. Structured logs record engine decisions, executed trades, and account lifecycle events.
- NFR-13. External market-data failures are handled gracefully (retry/back-off; skip tick rather than crash; never corrupt the ledger).

### 5.5 Security (single-operator scope)
- NFR-14. No secrets in source control; configuration via `.env` (git-ignored). `.env.example` documents required keys.
- NFR-15. Control endpoints (start engine, run backtest, mutate config) are protected by a shared operator secret/token; read endpoints may be open on the trusted VPS network but should not expose secrets.
- NFR-16. No real brokerage credentials are stored or used (paper-only).

### 5.6 Maintainability
- NFR-17. Strategies, fee model, data provider, and storage are modular behind interfaces so each can be swapped or extended.
- NFR-18. Code is tested: unit tests for fee math, account ledger, split enforcement, and each strategy; integration tests for a backtest run and the dashboard API.

---

## 6. Data Model (logical)

- **Account**: id, status (active|archived), created_at, closed_at?, starting_capital_cents, cash_cents.
- **Position**: id, account_id, symbol, quantity, avg_entry_price_cents, opened_at, closed_at? (open positions have null closed_at).
- **Trade**: id, account_id, symbol, side (buy|sell), quantity, price_cents, fee_cents, realized_pnl_cents (for closing trades), strategy_name, executed_at, data_split.
- **PriceBar (cache)**: symbol, timestamp, open, high, low, close, volume, interval (1d/1m/etc.), split_label (train|validation|test).
- **BacktestRun**: id, strategy_name, params (json), data_split, period_start, period_end, metrics (json: total_return, win_rate, max_drawdown, sharpe), created_at.

(Exact storage/typing decisions deferred to architecture; monetary fields stored as integer cents.)

---

## 7. Success Criteria

The MVP is **done** when:

1. **Lifecycle works end-to-end**: starting from a fresh database, the bot opens a $10,000 account, executes simulated trades with fees deducted, and — when forced to the floor — auto-archives the account and opens a new one. Verifiable via dashboard and DB.
2. **Three strategies run**: day, swing, and position strategies each produce trades in a backtest, and the selector picks among them by documented rules.
3. **Anti-overfitting enforced**: attempting to read test-split data outside final-evaluation mode raises an error (covered by a passing test); each run records its split.
4. **Dashboard delivers core views**: daily view (today's trades, per-trade P&L, running balance, fees), weekly view (summary + equity chart), and account switcher/history all render correct data for the active and archived accounts.
5. **Fees & ledger are correct**: a unit test proves fee math and that summing trades+fees reconciles to the account balance (NFR-9).
6. **Runs on Docker Compose**: `./run.sh start` brings up DB + API + frontend; `./run.sh test` runs the suite green; the engine runs on a schedule.
7. **No real-money paths exist**: code review and security review confirm there is no live-broker order routing and no real credentials.

### Acceptance metrics
- All user stories A1–G1 demonstrably satisfied.
- Test suite green; ledger reconciliation test passes; split-enforcement test passes.
- Dashboard daily/weekly/history views match underlying DB data for at least one busted+recycled account scenario.

---

## 8. Out of Scope (MVP)

- Real-money trading, live broker order execution, or any path that places real orders.
- Multi-user support, user registration, role management, OAuth/social login.
- Options, futures, crypto, forex, or non-US equities (US stocks only).
- Tax-lot accounting, wash-sale rules, margin/leverage, short selling beyond what a simple strategy needs (short selling itself is out of scope for MVP unless trivially supported; default long-only).
- Real-time tick/level-2 data, sub-second execution, or HFT.
- Mobile native apps; only a responsive web dashboard.
- Cloud-managed deployment (Kubernetes, serverless); MVP targets a single VPS with Docker Compose.
- Email/SMS/push alerting (structured logs only for MVP).
- Claude API features — explicitly deferred to the architecture phase, which will decide whether/where Claude adds value without draining API credits.

---

## 9. Assumptions

- **A-1.** Single trusted operator; the VPS is not a public multi-tenant host. (If the dashboard is internet-exposed, a minimal access gate is added — see NFR-15.)
- **A-2.** `yfinance` (Yahoo Finance) is acceptable as the MVP data source; rate/availability limits are tolerable for a single watchlist. Alpaca free tier is a documented fallback.
- **A-3.** Daily bars are the primary timeframe for swing/position strategies; intraday (e.g., 1-minute) bars are used for the day-trading strategy where freely available. Where intraday free data is limited, the day strategy may operate on the finest interval the provider offers, documented in architecture.
- **A-4.** "Live" paper trading on free data may lag real time by the provider's delay; this is acceptable for simulation.
- **A-5.** Strategy selection rules can be simple and rule-based for MVP (e.g., trend/volatility regime); sophisticated ML-based selection is not required.
- **A-6.** A small default watchlist of liquid large-cap US tickers is acceptable for MVP.
- **A-7.** Fee constants (SEC fee, FINRA TAF rates) are configurable and seeded with current published values; keeping them exactly current over time is the operator's responsibility.
- **A-8.** Monetary precision uses integer cents (or Decimal) throughout.
- **A-9.** Time zone for "today"/"this week" and market hours is US Eastern (ET).

---

## 10. Open Questions (with default decisions)

Each is given a default so development is not blocked; architecture/operator may override.

- **Q-1.** Fill model: bar close vs. next-bar open? **Default:** next-bar open for backtests (reduces look-ahead bias); document in architecture.
- **Q-2.** Slippage modeling? **Default:** none for MVP (fees only); note as a future enhancement.
- **Q-3.** Position sizing default? **Default:** fixed fractional (e.g., risk a configurable % of equity per position).
- **Q-4.** Short selling? **Default:** long-only for MVP.
- **Q-5.** Engine tick frequency for live mode? **Default:** once per minute during market hours for the day strategy; once per day at/after close for swing/position. Architecture confirms scheduler design.
- **Q-6.** "Week" definition? **Default:** Monday–Friday trading week in ET.
- **Q-7.** Does Claude API add value (e.g., market-regime summarization, trade rationale narration)? **Deferred to architecture** with an explicit cost/credit constraint.

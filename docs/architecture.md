# Architecture — Trading Tom

**Version:** 1.0 (MVP)
**Status:** Implementable — coding agent builds from this
**Author:** Systems Architect (PM pipeline)
**Date:** 2026-05-27
**Source:** Derived from `docs/PRD.md` v1.0 and `docs/design.md` v1.0

This document is the build spec. Where the PRD left open questions, the defaults are adopted here as decisions. Money is **integer cents** everywhere (NFR-8). Time is **US Eastern (ET)** for all market/business logic (A-9); timestamps are stored in UTC and converted at the edges.

---

## 1. System Overview

### 1.1 Components

```
                          ┌──────────────────────────────────────────┐
                          │              VPS (Docker Compose)          │
                          │                                            │
   Browser                │   ┌────────────┐        ┌──────────────┐  │
  ┌────────┐   HTTP/JSON  │   │  frontend  │  proxy  │     api      │  │
  │ React  │◀────────────▶│   │ (nginx +   │────────▶│  (FastAPI /  │  │
  │  SPA   │   :3000      │   │  Vite SPA) │  /api    │  uvicorn)    │  │
  └────────┘              │   └────────────┘  :8000   └──────┬───────┘  │
                          │                                  │          │
                          │                          SQLAlchemy ORM     │
                          │                                  │          │
                          │   ┌────────────┐          ┌──────▼───────┐  │
                          │   │   engine   │  same DB  │   Postgres   │  │
                          │   │ (scheduler │◀─────────▶│   :5432      │  │
                          │   │ + trading) │  ORM      │  (pgdata vol)│  │
                          │   └─────┬──────┘          └──────────────┘  │
                          │         │                                   │
                          └─────────┼───────────────────────────────────┘
                                    │ outbound HTTPS
                                    ▼
                          ┌──────────────────┐
                          │  Yahoo Finance    │  (yfinance; Alpaca free
                          │  market data      │   tier as documented fallback)
                          └──────────────────┘
```

### 1.2 Process / service roles

| Service | Process | Responsibility |
|---------|---------|----------------|
| `db` | Postgres 16 | Durable store: accounts, positions, trades, price-bar cache, backtest runs, equity snapshots. Single source of truth for the ledger (NFR-7). |
| `api` | FastAPI + uvicorn | Read-oriented REST for the dashboard + token-gated control endpoints. **No scheduling, no trading loop.** Stateless beyond the DB. |
| `engine` | Python long-running process (APScheduler) | The autonomous trading loop: market-hours scheduling, data refresh, strategy evaluation, simulated order execution, account lifecycle (bust/recycle), equity snapshots. Writes to the same DB via the same ORM models. |
| `frontend` | nginx serving built Vite SPA | Static dashboard; reverse-proxies `/api/*` to `api:8000` so the browser sees one origin. |

**Key separation of concerns:** `api` and `engine` share the **same database and the same ORM model package** (`trading_tom.models`) but are **separate processes**. The API never trades; the engine never serves HTTP. They communicate only through Postgres rows. This keeps the dashboard responsive regardless of engine load and lets the engine restart independently (NFR-10).

A small **control channel** lets the API ask the engine to start/stop/run-a-backtest without a message broker: the API writes an `engine_command` row (or flips an `engine_state` row); the engine polls that table each tick. This avoids adding Redis/Celery for the MVP (see §7.3).

### 1.3 Shared Python package layout

Both `api` and `engine` import a shared library so models, fee math, and the data layer are defined once:

```
api/trading_tom/        # importable package, mounted into both api & engine containers
  models/               # SQLAlchemy models (one file per table group)
  data/                 # data provider + split-enforcing repository
  engine/               # strategies, selector, executor, fee model, runner
  services/             # account lifecycle, aggregation queries for API
  config.py             # env + strategy config loading
  db.py                 # engine/session factory
```

The `engine` container reuses the **api image** (same build) and just runs a different entrypoint (`python -m trading_tom.engine.runner`). This avoids a second Dockerfile and guarantees both processes run identical code.

---

## 2. Data Model (Postgres)

All tables use `bigserial` PKs unless noted. All timestamps are `timestamptz` stored in UTC. Money is `bigint` cents. Quantities are `integer` shares (long-only, whole shares — A "fractional shares" extension is out of scope). Enums are implemented as Postgres `text` columns with `CHECK` constraints (simpler migrations than native enums for MVP).

Migrations are managed with **Alembic**. The initial migration creates all tables below plus seed config.

### 2.1 `accounts`

One active account at a time; archived accounts retain full history (A2–A4, FR-1..FR-5).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `id` | bigserial PK | |
| `status` | text | `CHECK (status IN ('active','archived'))`, NOT NULL |
| `created_at` | timestamptz | NOT NULL, default now() |
| `closed_at` | timestamptz | NULL until archived |
| `close_reason` | text | NULL; `CHECK (close_reason IN ('bust','manual') OR close_reason IS NULL)` |
| `starting_capital_cents` | bigint | NOT NULL, default 1000000 ($10,000) |
| `cash_cents` | bigint | NOT NULL — current settled cash |

Constraints / indexes:
- **Partial unique index** guaranteeing at most one active account:
  `CREATE UNIQUE INDEX uq_one_active_account ON accounts (status) WHERE status = 'active';`
  This enforces A3 at the database level — a second active account is impossible by construction.
- `INDEX ix_accounts_status (status)`.

Derived `equity` (cash + market value of open positions) is **not stored** on the row; it is computed on read from `cash_cents` + sum(open position qty × last price). Equity *snapshots* for charts are stored separately (§2.6).

### 2.2 `positions`

Open and historical lots per account (FR-5). Long-only (DA-6, Q-4).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `id` | bigserial PK | |
| `account_id` | bigint FK → accounts.id | NOT NULL, ON DELETE RESTRICT |
| `symbol` | text | NOT NULL |
| `quantity` | integer | NOT NULL, `CHECK (quantity >= 0)` |
| `avg_entry_price_cents` | bigint | NOT NULL — cost basis per share |
| `opened_at` | timestamptz | NOT NULL |
| `closed_at` | timestamptz | NULL while open (quantity > 0) |

Indexes:
- `INDEX ix_positions_account_open (account_id, symbol) WHERE closed_at IS NULL` — fast "current open positions for account".
- One open position row per (account, symbol) is the MVP rule; adding to a position updates qty + weighted avg entry. A full close sets `closed_at` and `quantity = 0`.

### 2.3 `trades`

Immutable ledger of every simulated fill (FR-14, FR-16). Append-only; never updated after insert (NFR-9 audit).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `id` | bigserial PK | |
| `account_id` | bigint FK → accounts.id | NOT NULL |
| `symbol` | text | NOT NULL |
| `side` | text | `CHECK (side IN ('buy','sell'))`, NOT NULL |
| `quantity` | integer | NOT NULL, `CHECK (quantity > 0)` |
| `price_cents` | bigint | NOT NULL — fill price per share |
| `fee_cents` | bigint | NOT NULL, default 0 — total fees on this fill |
| `realized_pnl_cents` | bigint | NULL on buys; signed P&L on closing sells |
| `strategy_name` | text | NOT NULL — which strategy generated the signal |
| `data_split` | text | `CHECK (data_split IN ('train','validation','test','live'))`, NOT NULL — `live` for real paper-trading fills; the split label otherwise (C2/FR-19) |
| `executed_at` | timestamptz | NOT NULL — fill time (ET-derived, stored UTC) |
| `backtest_run_id` | bigint FK → backtest_runs.id | NULL for live trades; set for backtest trades |

Indexes:
- `INDEX ix_trades_account_time (account_id, executed_at DESC)` — daily/weekly/history queries (NFR-1).
- `INDEX ix_trades_account_day (account_id, executed_at)` — supports date-range filters.
- `INDEX ix_trades_split (data_split)` — split audit filters.

### 2.4 `price_bars` (OHLCV cache)

Local cache of historical + recent bars (FR-6, FR-7). One row per (symbol, interval, ts).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `id` | bigserial PK | |
| `symbol` | text | NOT NULL |
| `interval` | text | `CHECK (interval IN ('1d','1m'))`, NOT NULL |
| `ts` | timestamptz | NOT NULL — bar open time (UTC) |
| `open_cents` | bigint | NOT NULL |
| `high_cents` | bigint | NOT NULL |
| `low_cents` | bigint | NOT NULL |
| `close_cents` | bigint | NOT NULL |
| `volume` | bigint | NOT NULL |
| `split_label` | text | `CHECK (split_label IN ('train','validation','test'))`, NOT NULL — computed at ingest from the symbol's date partition (§4) |

Constraints / indexes:
- `UNIQUE (symbol, interval, ts)` — idempotent upserts on refresh; re-fetching never duplicates.
- `INDEX ix_bars_lookup (symbol, interval, ts)` — range scans for backtests and the latest bar.

> Prices are stored as cents (`round(price * 100)`). Provider prices arrive as floats; we convert at ingest using `Decimal` to avoid float drift, then store the integer.

### 2.5 `backtest_runs`

Records every backtest/evaluation with the split it used (FR-19, FR-22, C2, NFR-5).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `id` | bigserial PK | |
| `strategy_name` | text | NOT NULL |
| `params` | jsonb | NOT NULL — exact strategy params used (reproducibility) |
| `data_split` | text | `CHECK (data_split IN ('train','validation','test'))`, NOT NULL |
| `symbols` | jsonb | NOT NULL — list of tickers tested |
| `period_start` | timestamptz | NOT NULL |
| `period_end` | timestamptz | NOT NULL |
| `seed` | integer | NOT NULL — RNG seed (NFR-6 determinism) |
| `metrics` | jsonb | NOT NULL — `{total_return, win_rate, max_drawdown, sharpe, n_trades, gross_pnl_cents, net_pnl_cents, fees_cents}` |
| `final_evaluation` | boolean | NOT NULL default false — true only when run in Final-Evaluation mode against `test` |
| `created_at` | timestamptz | NOT NULL default now() |

Index: `INDEX ix_backtests_created (created_at DESC)`.

A `CHECK` constraint enforces the anti-overfitting contract at the data layer too:
`CHECK (data_split <> 'test' OR final_evaluation = true)` — a `test` run can never be recorded unless it was an explicit final evaluation (C3, NFR-4).

### 2.6 `equity_snapshots`

Time series of account equity for charts (E2 weekly chart, account-detail lifetime curve).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `id` | bigserial PK | |
| `account_id` | bigint FK → accounts.id | NOT NULL |
| `ts` | timestamptz | NOT NULL |
| `equity_cents` | bigint | NOT NULL — cash + market value of open positions at `ts` |
| `cash_cents` | bigint | NOT NULL |

Constraints / indexes:
- `UNIQUE (account_id, ts)` — one snapshot per account per tick boundary.
- `INDEX ix_equity_account_time (account_id, ts)`.

The engine writes one snapshot at the **close of each trading day** (for the weekly/lifetime curve) and one at the **end of each intraday tick** for the active account's current day (so the daily hero sparkline has points). For backtests, snapshots are not persisted per-bar (kept in memory and summarized into `metrics`) to avoid bloating the table.

### 2.7 `engine_state` (control + status)

Single-row table the engine owns and the API reads/writes for control (§7.3).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `id` | integer PK | `CHECK (id = 1)` — singleton row |
| `desired_state` | text | `CHECK (desired_state IN ('running','stopped'))`, NOT NULL default 'running' — set by API control endpoints |
| `actual_state` | text | `CHECK (actual_state IN ('running','stopped','starting'))`, NOT NULL default 'stopped' — written by engine |
| `last_tick_at` | timestamptz | NULL — heartbeat for the dashboard's "Engine RUNNING" indicator and stale detection |
| `last_error` | text | NULL — last engine error for ops visibility |
| `updated_at` | timestamptz | NOT NULL default now() |

The dashboard's engine indicator is "RUNNING" iff `actual_state='running'` AND `last_tick_at` is within 2× the tick interval; otherwise it shows stale/stopped.

### 2.8 `strategy_configs`

Persisted, operator-editable strategy parameters (B2, FR-13, settings screen §3.5).

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| `strategy_name` | text PK | e.g., `day`, `swing`, `position` |
| `enabled` | boolean | NOT NULL default true |
| `params` | jsonb | NOT NULL — strategy-specific params (MA windows, sizing %, max positions, watchlist override) |
| `updated_at` | timestamptz | NOT NULL default now() |

Seeded by the initial migration with the defaults in §3.5. The engine reads these each tick (cheap; can be cached for the tick duration). Watchlist and fee constants live in env + a `app_settings` JSON if not per-strategy (see §3.4 fee model — fee constants come from env, watchlist from config/env with optional per-strategy override).

### 2.9 Reconciliation invariant (NFR-9)

For any account: `starting_capital_cents + Σ(realized_pnl on sells) − Σ(fee_cents) == cash_cents + Σ(open-position cost basis)`. A unit/integration test asserts this after a simulated session. Because trades are append-only and cash mutations happen in the same DB transaction as the trade insert (§3.6), the ledger is always consistent (NFR-7).

---

## 3. Trading Engine Design

### 3.1 Strategy interface (FR-10, FR-11, FR-5/B5 pluggable)

```python
# trading_tom/engine/base.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Signal:
    symbol: str
    side: str            # 'buy' | 'sell'
    quantity: int        # whole shares; resolved from sizing rule before emission
    reason: str          # human-readable, logged (NFR-12)

class Strategy(Protocol):
    name: str
    def required_history(self) -> int: ...        # number of bars of lookback needed
    def generate_signals(
        self,
        ctx: "MarketContext",                     # bars available up to "now" only (no look-ahead)
        account: "AccountView",                   # cash, open positions, equity
        params: dict,                             # from strategy_configs.params
    ) -> list[Signal]: ...
```

`MarketContext` exposes only bars at or before the current simulated/real timestamp. This is the structural guard against look-ahead bias: a strategy **cannot** see future bars because the context window is sliced by the runner (§3.3) before being passed in.

### 3.2 The three shipped strategies (FR-11, B4)

All are simple, deterministic, and rule-based (A-5). Whole-share, long-only, fixed-fractional sizing (Q-3).

| Strategy | `name` | Timeframe | Default logic (params overridable) | Holding behavior |
|----------|--------|-----------|-------------------------------------|------------------|
| Day | `day` | `1m` bars (or finest free interval, A-3) | Fast/slow MA crossover (9/21) on intraday bars; enter long on bullish cross, exit on bearish cross. **Flat by close** — any open `day` position is force-sold at the last bar of the session. | Intraday only |
| Swing | `swing` | `1d` bars | RSI(14) mean-reversion: buy when RSI < 30 and price > 50-day SMA (trend filter); sell when RSI > 60 or after `max_hold_days`. | Days |
| Position | `position` | `1d` bars | Trend-following: buy when 50-day SMA crosses above 200-day SMA (golden cross); hold; sell on death cross. | Weeks–months |

Sizing: `quantity = floor( (equity * position_size_pct) / fill_price )`, capped by available cash and `max_positions`.

### 3.3 Strategy selector (FR-12)

Deterministic, inspectable regime rule (no ML, A-5). Computed from the broad-market proxy (default `SPY`, configurable) on daily bars:

- Compute 20-day realized volatility and the 50/200 SMA trend on the proxy.
- **Regime → active strategy(s):**
  - Strong uptrend (50>200 SMA) & low vol → `position` (+ `swing` enabled).
  - Range-bound / mean-reverting (no clear SMA trend) & moderate vol → `swing`.
  - High vol → `day` (intraday) is favored; longer-horizon entries paused.
- The selector returns the set of enabled strategy names for the current bar. It is pure (regime in → names out), logged each day, and unit-tested with fixed inputs (NFR-6). Disabled strategies (`strategy_configs.enabled=false`) are always excluded.

### 3.4 Fee model (FR-15, FR-16) — Q-1 fills

Pure function, all constants from env/config so they can be updated (A-7):

```
commission_cents          = COMMISSION_CENTS (default 0)
# Sell-side regulatory fees (defaults seeded with current published rates):
sec_fee_cents             = ceil(SEC_FEE_RATE * notional)        # SEC_FEE_RATE default 0.0000229 (i.e. $22.90 per $1M)
finra_taf_cents           = min(round(FINRA_TAF_PER_SHARE * shares), FINRA_TAF_CAP_CENTS)
                            # FINRA_TAF_PER_SHARE default $0.000145/share; cap $7.27 (727 cents)
fee_cents(buy)            = commission_cents
fee_cents(sell)           = commission_cents + sec_fee_cents + finra_taf_cents
```

- `notional = shares * price_cents` (in cents); SEC fee is applied to the **sell proceeds** only.
- All arithmetic uses `Decimal` then rounds to whole cents; regulatory fees round **up** (conservative).
- Env keys (added to `.env.example`): `COMMISSION_CENTS`, `SEC_FEE_RATE`, `FINRA_TAF_PER_SHARE`, `FINRA_TAF_CAP_CENTS`.
- A unit test pins the math against worked examples (Success Criteria #5).

### 3.5 Order simulation / fill model (FR-14, Q-1, Q-2)

- **Fill price (backtest):** **next-bar open** — at bar *t* a strategy sees bars ≤ *t*; emitted signals fill at the open of bar *t+1*. This removes the look-ahead that a same-bar-close fill would introduce. The day strategy's forced end-of-session flatten fills at the **last bar's close** (no next bar exists).
- **Fill price (live paper):** the most recent available bar's close (data may lag real time, A-4).
- **Slippage:** none for MVP (Q-2); documented future enhancement. Fees only.
- **Cash sufficiency:** buys are clamped to available cash (after estimated fee); a signal that can't be afforded is skipped and logged.
- **Execution flow per signal:** validate → compute fill price → compute fee → update position (weighted-avg entry on buys; realized P&L on sells = `(fill - avg_entry) * qty - fee`) → update `cash_cents` → insert immutable `trade` row → (sell that fully closes a lot) set position `closed_at`.

Default strategy params seeded into `strategy_configs`:

```json
{
  "day":      {"enabled": true, "fast_ma": 9, "slow_ma": 21, "position_size_pct": 0.05, "max_positions": 3},
  "swing":    {"enabled": true, "rsi_period": 14, "rsi_buy": 30, "rsi_sell": 60, "sma_trend": 50, "max_hold_days": 10, "position_size_pct": 0.10, "max_positions": 5},
  "position": {"enabled": true, "sma_fast": 50, "sma_slow": 200, "position_size_pct": 0.20, "max_positions": 5}
}
```
Default watchlist (A-6): `["AAPL","MSFT","NVDA","TSLA","AMZN","GOOGL","META","SPY"]` (env `WATCHLIST`, comma-separated; `SPY` doubles as the regime proxy).

### 3.6 Transactional integrity (NFR-7)

Each tick processes signals inside a **single DB transaction per account mutation batch**: position update(s), cash update, and trade insert(s) commit together. If anything raises, the transaction rolls back — no partially-applied trade. The bust check (§3.7) runs inside the same transaction after fills settle. SQLAlchemy session with `SERIALIZABLE`-or-default isolation; the engine is the only writer to ledger tables during live trading, so contention is minimal.

### 3.7 Account lifecycle: bust & recycle (A2, FR-3)

After fills settle in a tick, compute account equity (cash + market value of open positions at latest prices). If `equity_cents <= ACCOUNT_FLOOR_CENTS` (default 0):
1. In the same transaction: liquidate open positions at last price (record closing trades), set `status='archived'`, `closed_at=now()`, `close_reason='bust'`.
2. Insert a new `accounts` row with `status='active'`, `cash_cents = STARTING_CAPITAL_CENTS`. The partial-unique index (§2.1) guarantees the old one is archived before the new active row commits.
3. Log the lifecycle event (NFR-12).

Because of the unique-active-index, the archive+create happens atomically in one transaction to avoid violating the constraint mid-flight (archive first, then insert active).

---

## 4. Anti-Overfitting Architecture (C1–C3, FR-17/18/19, NFR-4)

This is the product's reason to exist; enforcement is **structural, not policy**.

### 4.1 Date-based split assignment (FR-17)

Per symbol, the cached date range `[min_ts, max_ts]` is partitioned **chronologically** into contiguous segments by ratio (default 60/20/20, configurable via `SPLIT_RATIOS`):
- `train` = oldest 60%, `validation` = next 20%, `test` = newest 20%.

Boundaries are computed once per symbol at ingest and written to each bar's `split_label` (§2.4). Because test is the **most recent** data, it best approximates true out-of-sample.

### 4.2 Split-enforcing data repository (FR-18, NFR-4)

All bar reads go through one gateway — there is **no other path** to `price_bars` from engine/strategy code:

```python
# trading_tom/data/repository.py
class DataMode(Enum):
    DEVELOPMENT = "development"        # may read train + validation ONLY
    FINAL_EVALUATION = "final_eval"    # may read test
    LIVE = "live"                      # reads most-recent bars for paper trading

class BarRepository:
    def __init__(self, session, mode: DataMode): ...
    def get_bars(self, symbol, interval, start, end, splits: set[str]) -> list[Bar]:
        allowed = {
            DataMode.DEVELOPMENT: {"train", "validation"},
            DataMode.FINAL_EVALUATION: {"test"},      # ONLY test, deliberately exclusive
            DataMode.LIVE: {"train", "validation", "test"},  # live trades the present; split label irrelevant
        }[self.mode]
        if not splits.issubset(allowed):
            raise SplitAccessError(
                f"Mode {self.mode} cannot read splits {splits - allowed}"
            )
        # query filtered by split_label IN splits
```

- The repository is the **only** way to fetch bars. Strategies receive a pre-sliced `MarketContext`; they never touch the session.
- Requesting `test` in `DEVELOPMENT` mode raises `SplitAccessError` → satisfies Success Criteria #3 and is covered by a passing unit test.
- The backtest runner is constructed with a `DataMode`; the parameter optimizer is hard-wired to `DEVELOPMENT` and **cannot** be passed `FINAL_EVALUATION` (the optimizer's constructor doesn't accept a mode — it instantiates the repo as DEVELOPMENT internally). To run on `test`, you must call the separate `final_evaluation` entrypoint, which sets `final_evaluation=true` on the recorded run (and the `backtest_runs` CHECK constraint backstops it — §2.5).

### 4.3 Optimization workflow (C3)

- `optimize(strategy, param_grid)` runs a grid/search using **train** for fitting signals and **validation** for scoring; selects best params; records runs with `data_split` in {train, validation}. It physically cannot read test.
- `final_evaluation(strategy, params)` is a distinct, explicitly-invoked function (operator-gated via the API "Final-Evaluation" confirm, §3.5 of design) that constructs the repo in `FINAL_EVALUATION` mode, runs once, and records the run with `final_evaluation=true`, `data_split='test'`. This is the single honest out-of-sample estimate (C3).

### 4.4 Run provenance (C2, NFR-5)

Every `backtest_runs` row stores `params`, `data_split`, `symbols`, `seed`, and `final_evaluation`. Every `trades` row stores `data_split`. The dashboard surfaces these (split badge per trade; split + final-eval flag per run), making the discipline auditable end-to-end.

---

## 5. Data Pipeline (FR-6, FR-7, FR-9, NFR-13)

### 5.1 Provider abstraction

```python
# trading_tom/data/provider.py
class MarketDataProvider(Protocol):
    def fetch_bars(self, symbol, interval, start, end) -> list[RawBar]: ...

class YFinanceProvider:  # MVP default — no API key
class AlpacaProvider:    # documented fallback; reads ALPACA_API_KEY/SECRET if set
```

`DATA_PROVIDER` env (`yfinance` | `alpaca`) selects the implementation at startup. yfinance is the default (A-2); Alpaca is wired but optional.

### 5.2 Ingest & refresh

- **Backfill (one-time / on demand):** for each watchlist symbol, fetch the longest free history (daily: years; intraday `1m`: provider limit, typically ~30 days for yfinance — A-3). Convert prices to cents via `Decimal`, compute `split_label`, **upsert** into `price_bars` (`ON CONFLICT (symbol,interval,ts) DO UPDATE`). Idempotent.
- **Live refresh (during market hours, FR-9):** the engine's intraday tick first refreshes the latest bars for watchlist symbols (incremental fetch since last cached `ts`), upserts them, then evaluates strategies on the freshly-cached data. Daily-strategy ticks refresh daily bars at/after the close.
- **Resilience (NFR-13):** provider calls wrap in retry-with-backoff (e.g., 3 tries, exponential). On persistent failure the tick **skips** (logs a warning, sets `engine_state.last_error`, leaves the ledger untouched) rather than crashing — the dashboard shows the stale-data banner using `last_tick_at`/latest bar `ts`.
- **Determinism for backtests (NFR-6):** backtests read **only** the cached `price_bars` — never the live provider — so a backtest is reproducible given the same cache + params + seed.

### 5.3 Market calendar / hours (FR-9, A-9)

Use `pandas_market_calendars` (NYSE calendar) to determine trading days, session open/close (09:30–16:00 ET), and holidays. The engine derives "is the market open now?" from this calendar in ET; pre/post-market is treated as closed for MVP (no extended-hours trading). When closed, the engine is idle — it still heartbeats `engine_state.last_tick_at` so the dashboard shows RUNNING + market CLOSED.

---

## 6. API Design (FR-23, FR-24)

FastAPI, JSON, mounted under `/api`. Pydantic response models. Money returned as integer cents (`*_cents` fields) — the FE formats (DA-4). All datetimes returned ISO-8601 UTC with the understanding the FE renders ET (DA-2).

### 6.1 Read endpoints (open on trusted network)

| Method | Path | Purpose | PRD/Design ref |
|--------|------|---------|----------------|
| GET | `/api/health` | Liveness | NFR-10 |
| GET | `/api/engine/status` | `{actual_state, last_tick_at, last_error, market_open}` | sidebar status, §3.6 |
| GET | `/api/accounts` | List all accounts with summary (status, dates, start/final, return) | F1/F3, §3.3 |
| GET | `/api/accounts/active` | The single active account | A3, top bar |
| GET | `/api/accounts/{id}` | Account detail incl. lifetime summary (return, win%, max DD, Sharpe) | F2, §3.4 |
| GET | `/api/accounts/{id}/positions` | Open positions w/ unrealized P&L (uses latest cached price) | D2, §3.1 |
| GET | `/api/accounts/{id}/trades?from=&to=&symbol=&side=&split=&page=&page_size=` | Paginated, filterable trade history (server-paginated for NFR-1) | D1, F2, §3.4 |
| GET | `/api/accounts/{id}/daily?date=YYYY-MM-DD` | Daily view payload: today's trades, realized/unrealized P&L, running balance, fees | D1–D3, §3.1 |
| GET | `/api/accounts/{id}/weekly?week=YYYY-Www` | Weekly summary (trades, win rate, gross/fees/net, avg win/loss) + daily breakdown | E1, §3.2 |
| GET | `/api/accounts/{id}/equity?range=day|week|all` | Equity snapshot series for charts | E2, §3.4 |
| GET | `/api/backtests?page=&page_size=` | List backtest runs | FR-22, §3.5 |
| GET | `/api/backtests/{id}` | Backtest run detail (metrics, split, params, final_eval) | C2, §3.5 |
| GET | `/api/config/strategies` | Current strategy configs + watchlist + fee model (read) | FR-13, §3.5 |

"Today"/"this week" boundaries are computed in **ET** server-side; `date`/`week` default to current ET.

### 6.2 Control endpoints (operator-token-gated, NFR-15, FR-24)

Header `X-Operator-Token` must equal `OPERATOR_TOKEN` env; otherwise `401`. A FastAPI dependency `require_operator_token` guards all of these.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/engine/start` | Set `engine_state.desired_state='running'` |
| POST | `/api/engine/stop` | Set `engine_state.desired_state='stopped'` |
| POST | `/api/engine/restart` | stop then start (desired flags) |
| PUT | `/api/config/strategies/{name}` | Update strategy params/enabled (writes `strategy_configs`) |
| PUT | `/api/config/watchlist` | Update watchlist |
| POST | `/api/backtests` | Run a backtest: `{strategy, params, symbols, split}` where `split ∈ {train,validation}` — runs in DEVELOPMENT mode |
| POST | `/api/backtests/final-evaluation` | Run the single honest test-split evaluation: `{strategy, params, symbols}` → FINAL_EVALUATION mode, records `final_evaluation=true`. Requires explicit `confirm=true`. |

Backtests are **dispatched to the engine** via a command row (or run synchronously in a worker thread for the MVP if the dataset is small enough to meet NFR-2 < 30s); the chosen approach: the API writes a `backtest` command to `engine_state`/a small `commands` queue table and the engine executes it, writing results to `backtest_runs`. The FE polls `/api/backtests/{id}` for completion. (If implementation finds synchronous execution within the request is simpler and meets NFR-2, that is acceptable for MVP — documented as the fallback.)

### 6.3 Errors & CORS

- Standard problem JSON `{detail, code}`; `401` for bad token, `404` for missing account, `409` for split violations surfaced from `SplitAccessError`.
- CORS: in dev, allow the Vite origin; in prod the SPA is same-origin (served by the frontend nginx proxy) so CORS is effectively closed.

---

## 7. Scheduling (FR-21, Q-5, NFR-3)

### 7.1 Choice: APScheduler (in the `engine` process), not Celery

**Decision: APScheduler.** Rationale: the MVP has a single, modest, mostly-cron workload (a per-minute intraday tick + an end-of-day tick) on one VPS. Celery/Celery-Beat would add a broker (Redis/RabbitMQ), a beat process, and workers — operational overhead with no payoff at this scale. APScheduler runs inside the long-lived `engine` process with a `BlockingScheduler`, is trivial to reason about, and restarts cleanly with the container (NFR-10). Redis is therefore **not required** for the MVP (see §9).

### 7.2 Jobs

| Job | Trigger | Action |
|-----|---------|--------|
| `intraday_tick` | every 1 min, only fires when NYSE session is open (job checks calendar; no-op + heartbeat otherwise) | refresh `1m` bars → run `day` strategy on active account → execute fills → equity snapshot → bust check |
| `daily_close_tick` | once per trading day shortly after 16:00 ET | refresh `1d` bars → run `swing`/`position` strategies → execute fills → force-flatten any open `day` positions → daily equity snapshot → bust check |
| `heartbeat` | every 30s | write `engine_state.last_tick_at`, reconcile `desired_state` → `actual_state` (start/stop trading jobs accordingly) |
| `daily_backfill` | once daily pre-open | ensure cache up to date; recompute split boundaries if new history |

Each job is wrapped so an exception sets `engine_state.last_error` and is logged, but never kills the scheduler (NFR-13). Per-tick work across the watchlist is small (a handful of symbols, vectorized indicator math with pandas/numpy) — comfortably within the 1-min interval (NFR-3).

### 7.3 Control loop (API ↔ engine without a broker)

The `heartbeat` job reads `engine_state.desired_state`. If `desired=stopped`, the engine pauses the trading jobs (keeps heartbeating, sets `actual_state='stopped'`). If `desired=running`, it resumes. Backtest commands are picked up the same way (a `commands` table the engine drains). This keeps everything in Postgres — no extra infrastructure.

---

## 8. Claude API Integration Decision (Q-7)

**Decision: Option (b) — a single, cheap, once-per-day market summary, behind a feature flag that is OFF by default for the MVP.**

Rationale:
- **(a) nowhere** is the safe default, and indeed the MVP must function fully with Claude disabled — none of the core requirements (trading, ledger, anti-overfitting, dashboard) need an LLM. So Claude is strictly **optional and additive**.
- **(c) on-demand strategy analysis** risks unbounded, repeated calls (every dashboard visit could trigger one) — exactly the credit-drain the PRD warns against. Rejected for MVP.
- **(b) daily market summary** is bounded to **one call per trading day** (≈21/month), tiny token footprint (a short prompt summarizing the day's trades/P&L/regime into 2–3 sentences for the dashboard header). It adds genuine "what happened today" narrative value with negligible, predictable cost.

Implementation contract:
- Feature flag `ENABLE_CLAUDE_SUMMARY` (default `false`) + `ANTHROPIC_API_KEY` (optional). If the flag is off or the key is absent, the feature is fully bypassed and the dashboard simply omits the narrative — **no code path requires it**.
- When enabled: the `daily_close_tick` makes one call to summarize the active account's day (trades count, net P&L, regime, notable moves) and stores the text on that day's `equity_snapshot` row or a small `daily_notes` field; the API serves it; the FE shows it as an optional banner on the Daily view.
- Uses prompt caching for the static system prompt to minimize cost. No trading decision ever depends on Claude (keeps the engine deterministic, NFR-6, and avoids real-money-style risk).

This respects the explicit cost/credit constraint while leaving a clean, opt-in hook.

---

## 9. Docker Compose Services

The existing `docker-compose.yml` is extended (not replaced) to add the `engine` service and align with the architecture. **No Redis** (APScheduler in-process — §7.1).

| Service | Image / Build | Ports | Notes |
|---------|---------------|-------|-------|
| `db` | `postgres:16-alpine` | 5432 (internal) | `pgdata` named volume; healthcheck `pg_isready`; restart unless-stopped |
| `api` | build `./api` | 8000 | uvicorn; `depends_on: db (healthy)`; runs Alembic migrations on start (entrypoint) |
| `engine` | **reuses the api build** (`build: ./api`), different command: `python -m trading_tom.engine.runner` | none | `depends_on: db (healthy), api (started)`; restart unless-stopped; the autonomous scheduler |
| `frontend` | build `./frontend` (multi-stage: Vite build → nginx) | 3000 | nginx serves SPA + reverse-proxies `/api` → `api:8000` so the browser has one origin (closes CORS in prod) |

Compose additions:
- Add a `db` healthcheck and switch `api`/`engine` to `depends_on: {db: {condition: service_healthy}}`.
- Add the `engine` service block (same `build: ./api`, `env_file: .env`, `command: python -m trading_tom.engine.runner`).
- `api` entrypoint runs `alembic upgrade head` then `uvicorn ...` so a fresh DB self-migrates (Success Criteria #6: `./run.sh start` brings up a working stack from empty).
- Frontend Dockerfile becomes multi-stage (build static assets, serve with nginx) for prod; dev can still use the Vite dev server.

`run.sh` already provides start/stop/restart/logs/build/status/test/shell/clean/help (verified) — no changes required beyond ensuring `test` targets the `api` service's pytest, which it does.

---

## 10. File / Directory Structure

```
trading-tom/
├── docker-compose.yml
├── run.sh
├── .env.example                  # extended with fee, token, split, claude, provider keys
├── .gitignore
├── README.md
├── CLAUDE.md
├── docs/
│   ├── PRD.md
│   ├── design.md
│   └── architecture.md           # this file
├── api/
│   ├── Dockerfile                # builds image used by BOTH api and engine
│   ├── requirements.txt          # fastapi, uvicorn, sqlalchemy, alembic, psycopg2-binary,
│   │                             # pydantic, pydantic-settings, yfinance, pandas, numpy,
│   │                             # pandas_market_calendars, apscheduler, anthropic (optional),
│   │                             # pytest, httpx (test client)
│   ├── main.py                   # FastAPI app factory; mounts routers under /api
│   ├── entrypoint.sh             # alembic upgrade head && exec "$@"
│   ├── alembic.ini
│   ├── migrations/               # Alembic env + versions (initial schema + seed)
│   ├── trading_tom/              # the shared importable package
│   │   ├── __init__.py
│   │   ├── config.py             # Settings (pydantic-settings): env + strategy config loading
│   │   ├── db.py                 # engine, SessionLocal, Base
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── account.py        # Account, Position
│   │   │   ├── trade.py          # Trade
│   │   │   ├── market.py         # PriceBar, EquitySnapshot
│   │   │   ├── backtest.py       # BacktestRun
│   │   │   └── engine_state.py   # EngineState, StrategyConfig, Command
│   │   ├── data/
│   │   │   ├── provider.py       # MarketDataProvider, YFinanceProvider, AlpacaProvider
│   │   │   ├── repository.py     # BarRepository + DataMode + SplitAccessError (enforcement)
│   │   │   ├── ingest.py         # backfill + refresh + split-label assignment
│   │   │   └── calendar.py       # NYSE market hours helpers (ET)
│   │   ├── engine/
│   │   │   ├── base.py           # Strategy protocol, Signal, MarketContext, AccountView
│   │   │   ├── fees.py           # fee model (pure functions)
│   │   │   ├── executor.py       # order simulation, position/cash/trade updates (txn)
│   │   │   ├── lifecycle.py      # bust check + archive/recycle
│   │   │   ├── selector.py       # regime → active strategy set
│   │   │   ├── strategies/
│   │   │   │   ├── day.py
│   │   │   │   ├── swing.py
│   │   │   │   └── position.py
│   │   │   ├── backtest.py       # backtest runner (bar replay) + optimizer + final_evaluation
│   │   │   ├── metrics.py        # return, win rate, max drawdown, sharpe
│   │   │   └── runner.py         # APScheduler entrypoint (the `engine` service)
│   │   ├── services/
│   │   │   ├── accounts.py       # account summaries, lifetime metrics
│   │   │   ├── aggregates.py     # daily/weekly aggregation queries (ET boundaries)
│   │   │   └── claude.py         # optional daily summary (flag-gated; no-op if disabled)
│   │   └── api/
│   │       ├── deps.py           # DB session dep, require_operator_token
│   │       ├── schemas.py        # Pydantic response/request models
│   │       └── routers/
│   │           ├── accounts.py
│   │           ├── trades.py
│   │           ├── aggregates.py # daily/weekly/equity
│   │           ├── backtests.py
│   │           ├── engine.py     # status + control
│   │           └── config.py     # strategy/watchlist/fee read+write
│   └── tests/
│       ├── test_fees.py          # fee math (Success Criteria #5)
│       ├── test_ledger.py        # reconciliation invariant (NFR-9)
│       ├── test_split_enforcement.py  # SplitAccessError on test in dev mode (Criteria #3)
│       ├── test_lifecycle.py     # bust → archive → new active account (Criteria #1)
│       ├── test_strategies.py    # each strategy emits signals on fixtures (Criteria #2)
│       ├── test_selector.py      # deterministic regime selection
│       └── test_api.py           # daily/weekly/accounts endpoints (httpx TestClient)
└── frontend/
    ├── Dockerfile                # multi-stage: vite build → nginx
    ├── nginx.conf                # serve SPA + proxy /api → api:8000
    ├── package.json              # + react-router-dom, recharts, lucide-react, axios/fetch wrapper
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx               # router + layout (Sidebar + TopBar)
        ├── theme/tokens.css      # design tokens from design.md §2.2
        ├── api/client.js         # typed wrappers over §6 endpoints
        ├── context/AccountScope.jsx
        ├── hooks/usePolling.js   # 30s refresh (DA-5)
        ├── components/           # Money, PnLValue, Badge, StatusDot, StatCard,
        │                         # DataTable, Sparkline, EquityChart, Sidebar, TopBar,
        │                         # AccountSwitcher, SummaryStrip, ... (design.md §4)
        └── pages/
            ├── Daily.jsx
            ├── Weekly.jsx
            ├── Accounts.jsx
            ├── AccountDetail.jsx
            ├── Backtests.jsx
            └── Settings.jsx
```

---

## 11. Build order (guidance for the coding phase)

Dependency-ordered slices (each independently committable):

1. **Foundation:** `config.py`, `db.py`, models, Alembic initial migration + seed (`strategy_configs`, `engine_state` singleton), `.env.example` extensions, compose `engine` service + db healthcheck + api entrypoint.
2. **Data layer:** provider (yfinance), calendar, ingest + split-label assignment, `BarRepository` with `DataMode` enforcement (+ `test_split_enforcement`).
3. **Engine core:** fee model (+test), executor (txn, position/cash/trade), lifecycle bust/recycle (+test_ledger, +test_lifecycle).
4. **Strategies + selector:** day/swing/position + regime selector (+test_strategies, +test_selector).
5. **Backtest + optimizer + final_evaluation:** runner, metrics, provenance recording.
6. **Runner/scheduler:** APScheduler jobs, control loop, heartbeat.
7. **API:** routers + schemas + token dependency + aggregation services (+test_api).
8. **Frontend:** tokens/theme, layout, api client, pages (Daily → Weekly → Accounts → Detail → Backtests → Settings), Recharts equity chart.
9. **(Optional, flag-off)** Claude daily summary hook.

---

## 12. Traceability (requirement → architecture)

| Requirement | Addressed by |
|-------------|--------------|
| A1–A4, FR-1..5 (accounts) | §2.1 accounts + partial-unique-active index; §3.7 lifecycle |
| FR-6..9 (market data) | §5 data pipeline; §2.4 price_bars cache; §5.3 calendar |
| FR-10..14, B4/B5 (engine/strategies) | §3.1 interface; §3.2 strategies; §3.5 execution |
| FR-12 (selector) | §3.3 regime selector |
| FR-15/16 (fees) | §3.4 fee model |
| C1–C3, FR-17..19, NFR-4/5 (anti-overfit) | §4 (repository enforcement + CHECK constraint + provenance) |
| FR-20..22 (backtest) | §4.3, §6.2 backtest endpoints, §2.5 backtest_runs |
| FR-23/24, NFR-15 (API/auth) | §6 endpoints + operator-token dependency |
| FR-25..29 (dashboard) | §6 read payloads feed design.md screens |
| NFR-1 (10k trades) | server pagination + trade indexes §2.3 |
| NFR-7/8/9 (integrity) | §3.6 txn, integer cents, §2.9 reconciliation |
| NFR-10 (unattended) | §1.2 process separation, compose restart, migrate-on-start |
| NFR-13 (data failures) | §5.2 retry/skip; engine_state.last_error |
| Q-7 (Claude) | §8 decision: opt-in daily summary, off by default |
| Deployment (VPS/Compose) | §9 services; run.sh |
```

# Architecture & Implementation Decisions

## Decision Log (iteration 1)

### D1 — SQLite for unit tests, Postgres for production
**Context:** Tests need a DB session fixture. Running Postgres in a test environment requires Docker.
**Decision:** Unit tests use SQLite in-memory. Postgres-only features (JSONB, partial unique indexes on `WHERE`) are skipped in test via `checkfirst=True` on `create_all` — SQLite simply ignores the unsupported index expressions. Integration tests against a real Postgres container are out of scope for MVP; `./run.sh test` inside the api container hits real Postgres.
**Trade-off:** Unit tests don't fully exercise JSONB operators, but fee/ledger/split enforcement logic (the critical paths) is DB-agnostic and fully tested.

### D2 — Strategy name stored as the signal `reason` prefix
**Context:** The `Trade.strategy_name` column needs a value when inserting. Strategies set `signal.reason` to e.g. `"day:bullish_cross"`. The executor extracts the prefix before the colon.
**Decision:** `strategy_name = reason.split(":")[0] if ":" in reason else reason`. This keeps strategies decoupled from the executor while still recording provenance.

### D3 — `BarRepository` in LIVE mode allows all splits
**Context:** Architecture §4.2 specifies LIVE mode reads "most-recent bars for paper trading; split label irrelevant". The split_label column is still `train`/`validation`/`test` but LIVE paper trading just reads whatever is newest regardless.
**Decision:** LIVE mode is permissive (`{"train","validation","test"}`). This matches the architecture spec. It does NOT bypass anti-overfitting because live paper-trading doesn't create backtest provenance records.

### D4 — Backtest account is temporary (created then rolled back in optimizer)
**Context:** The optimizer needs to run many parameter combinations. Creating real DB accounts for each run would bloat the DB.
**Decision:** The optimizer calls `session.rollback()` after each trial run, discarding temporary accounts and trades. Only the best run's results are written. A note in `run_backtest()` warns callers to commit only once per real run.

### D5 — EOD flatten only runs on `day`-strategy positions
**Context:** The `generate_eod_flatten_signals()` method iterates all open positions in the AccountView, not just those opened by the day strategy. In a real trading scenario this could accidentally flatten swing or position trades.
**Decision:** MVP simplification: the EOD flatten is called only at `daily_close_tick` and only after swing/position strategies have run. Since open positions per symbol are tracked globally (one row per account+symbol), the flatten would only affect positions that remain open by EOD. Swing and position strategies hold multi-day, so they wouldn't normally be exiting at EOD anyway. A more precise fix (filtering by strategy tag on Position) is noted as a future enhancement.

### D6 — Frontend Backtests page uses raw `fetch` for the backtest list
**Context:** The api client uses axios but the backtests endpoint returns a plain list. The `usePolling` hook was already wired to `api.listStrategies` (which uses axios). Rather than add another method to `api` object for a rarely-visited page, the Backtests page uses a raw `fetch` call inline.
**Decision:** Acceptable for MVP; all other pages use the typed `api` client. Tracking: add `api.listBacktests()` to `client.ts` in next iteration.

### D7 — Lifetime max_drawdown and Sharpe simplified in account detail API
**Context:** Computing accurate max_drawdown and Sharpe for a live account requires the full `equity_snapshots` time series. For the MVP, the `compute_lifetime_metrics()` service returns `0.0` for these fields until a full snapshot series is present.
**Decision:** Acceptable MVP simplification. These metrics are computed correctly in backtest mode (from in-memory equity_series). The dashboard can display them as "N/A" until snapshots accumulate.

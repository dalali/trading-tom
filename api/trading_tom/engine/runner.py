"""
Trading engine runner — APScheduler-based live paper trading loop.

Jobs (architecture §7.2):
  - intraday_tick: every 1min during NYSE hours → day strategy
  - daily_close_tick: ~16:05 ET → swing/position strategies + EOD flatten
  - heartbeat: every 30s → update engine_state, reconcile desired/actual state
  - daily_backfill: 6 AM ET weekdays → ensure data cache up to date
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.exc import SQLAlchemyError

from trading_tom.db import SessionLocal
from trading_tom.engine.lifecycle import (
    bust_check_and_recycle,
    get_active_account,
    compute_equity,
)
from trading_tom.engine.selector import select_strategies
from trading_tom.engine.executor import execute_signal, InsufficientFundsError
from trading_tom.engine.base import MarketContext, AccountView, PositionView
from trading_tom.engine.strategies.day import DayMACrossStrategy
from trading_tom.data.calendar import is_market_open
from trading_tom.data.repository import BarRepository, DataMode
from trading_tom.data.ingest import refresh_latest, backfill
from trading_tom.models.account import Account, Position
from trading_tom.models.engine_state import EngineState, StrategyConfig
from trading_tom.models.market import EquitySnapshot

logger = logging.getLogger(__name__)

_ACTUAL_STATE = "stopped"


def _get_or_create_engine_state(session) -> EngineState:
    state = session.query(EngineState).filter_by(id=1).first()
    if state is None:
        state = EngineState(
            id=1,
            desired_state="running",
            actual_state="stopped",
            updated_at=datetime.now(timezone.utc),
        )
        session.add(state)
        session.commit()
    return state


def _build_account_view(session, account: Account, latest_prices: dict[str, int]) -> AccountView:
    open_pos = (
        session.query(Position)
        .filter(Position.account_id == account.id, Position.closed_at.is_(None), Position.quantity > 0)
        .all()
    )
    equity = account.cash_cents + sum(
        p.quantity * latest_prices.get(p.symbol, p.avg_entry_price_cents)
        for p in open_pos
    )
    return AccountView(
        account_id=account.id,
        cash_cents=account.cash_cents,
        equity_cents=equity,
        open_positions=[
            PositionView(p.symbol, p.quantity, p.avg_entry_price_cents) for p in open_pos
        ],
    )


def _get_enabled_strategy_names(session) -> set[str]:
    configs = session.query(StrategyConfig).filter_by(enabled=True).all()
    return {c.strategy_name for c in configs}


def _get_strategy_params(session, name: str) -> dict:
    config = session.query(StrategyConfig).filter_by(strategy_name=name).first()
    return config.params if config else {}


def intraday_tick():
    """Every 1 min: refresh 1m bars, run day strategy, execute fills, snapshot."""
    global _ACTUAL_STATE
    session = SessionLocal()
    try:
        state = _get_or_create_engine_state(session)
        if state.desired_state == "stopped":
            logger.debug("Engine desired=stopped; skipping intraday_tick")
            return

        if not is_market_open():
            # Still heartbeat but no trading
            state.last_tick_at = datetime.now(timezone.utc)
            state.actual_state = "running"
            session.commit()
            return

        from trading_tom.config import settings
        tickers = settings.watchlist_tickers

        # Refresh intraday bars
        refresh_latest(session, tickers, interval="1m")

        account = get_active_account(session)
        if account is None:
            logger.warning("No active account; skipping tick")
            return

        repo = BarRepository(session, DataMode.LIVE)
        bars_map: dict = {}
        latest_prices: dict[str, int] = {}
        for symbol in tickers:
            bars = repo.get_bars(symbol, "1m")
            if bars:
                bars_map[symbol] = bars
                latest_prices[symbol] = bars[-1].close_cents

        ctx = MarketContext(
            as_of=datetime.now(timezone.utc),
            bars=bars_map,
            latest_prices=latest_prices,
        )

        enabled = _get_enabled_strategy_names(session)
        # Intraday: only day strategy
        day_strategies = [s for s in select_strategies(ctx, enabled) if s.name == "day"]

        for strategy in day_strategies:
            params = _get_strategy_params(session, strategy.name)
            account_view = _build_account_view(session, account, latest_prices)
            try:
                signals = strategy.generate_signals(ctx, account_view, params)
            except Exception as exc:
                logger.error("Strategy %s error: %s", strategy.name, exc)
                continue

            for signal in signals:
                fill_price = latest_prices.get(signal.symbol)
                if fill_price is None:
                    continue
                try:
                    execute_signal(session, signal, account, fill_price, data_split="live")
                except InsufficientFundsError as e:
                    logger.debug("Skipped signal: %s", e)
                except Exception as e:
                    logger.error("Executor error: %s", e)

        account = bust_check_and_recycle(session, account, latest_prices)

        # Write equity snapshot
        equity = compute_equity(session, account, latest_prices)
        snap = EquitySnapshot(
            account_id=account.id,
            ts=datetime.now(timezone.utc),
            equity_cents=equity,
            cash_cents=account.cash_cents,
        )
        session.add(snap)

        state.last_tick_at = datetime.now(timezone.utc)
        state.actual_state = "running"
        state.last_error = None
        session.commit()
        _ACTUAL_STATE = "running"

    except Exception as exc:
        logger.exception("intraday_tick error: %s", exc)
        try:
            session.rollback()
            state = _get_or_create_engine_state(session)
            state.last_error = str(exc)
            session.commit()
        except Exception:
            pass
    finally:
        session.close()


def daily_close_tick():
    """After 16:05 ET: refresh daily bars, run swing/position, flatten day positions."""
    session = SessionLocal()
    try:
        state = _get_or_create_engine_state(session)
        if state.desired_state == "stopped":
            return

        from trading_tom.config import settings
        tickers = settings.watchlist_tickers

        # Refresh daily bars
        refresh_latest(session, tickers, interval="1d")

        account = get_active_account(session)
        if account is None:
            return

        repo = BarRepository(session, DataMode.LIVE)
        bars_map: dict = {}
        latest_prices: dict[str, int] = {}
        for symbol in tickers:
            bars = repo.get_bars(symbol, "1d")
            if bars:
                bars_map[symbol] = bars
                latest_prices[symbol] = bars[-1].close_cents

        ctx = MarketContext(
            as_of=datetime.now(timezone.utc),
            bars=bars_map,
            latest_prices=latest_prices,
        )

        enabled = _get_enabled_strategy_names(session)
        daily_strategies = [s for s in select_strategies(ctx, enabled) if s.name != "day"]

        for strategy in daily_strategies:
            params = _get_strategy_params(session, strategy.name)
            account_view = _build_account_view(session, account, latest_prices)
            try:
                signals = strategy.generate_signals(ctx, account_view, params)
            except Exception as exc:
                logger.error("Strategy %s error: %s", strategy.name, exc)
                continue

            for signal in signals:
                fill_price = latest_prices.get(signal.symbol)
                if fill_price is None:
                    continue
                try:
                    execute_signal(session, signal, account, fill_price, data_split="live")
                except InsufficientFundsError as e:
                    logger.debug("Skipped signal: %s", e)
                except Exception as e:
                    logger.error("Executor error: %s", e)

        # Force-flatten open day positions
        day_strategy = DayMACrossStrategy()
        account_view = _build_account_view(session, account, latest_prices)
        eod_signals = day_strategy.generate_eod_flatten_signals(account_view, "day")
        for signal in eod_signals:
            fill_price = latest_prices.get(signal.symbol)
            if fill_price is None:
                continue
            try:
                execute_signal(session, signal, account, fill_price, data_split="live")
            except Exception as e:
                logger.error("EOD flatten error: %s", e)

        account = bust_check_and_recycle(session, account, latest_prices)

        # Daily equity snapshot
        equity = compute_equity(session, account, latest_prices)
        snap = EquitySnapshot(
            account_id=account.id,
            ts=datetime.now(timezone.utc),
            equity_cents=equity,
            cash_cents=account.cash_cents,
        )
        session.add(snap)

        state.last_tick_at = datetime.now(timezone.utc)
        state.last_error = None
        session.commit()

    except Exception as exc:
        logger.exception("daily_close_tick error: %s", exc)
        try:
            state = _get_or_create_engine_state(session)
            state.last_error = str(exc)
            session.commit()
        except Exception:
            pass
    finally:
        session.close()


def heartbeat():
    """Every 30s: update last_tick_at and reconcile desired ↔ actual state."""
    global _ACTUAL_STATE
    session = SessionLocal()
    try:
        state = _get_or_create_engine_state(session)
        state.last_tick_at = datetime.now(timezone.utc)
        if state.desired_state == "stopped":
            state.actual_state = "stopped"
            _ACTUAL_STATE = "stopped"
        else:
            state.actual_state = _ACTUAL_STATE
        session.commit()
    except Exception as exc:
        logger.warning("Heartbeat error: %s", exc)
    finally:
        session.close()


def daily_backfill_job():
    """6 AM ET weekdays: backfill data cache."""
    session = SessionLocal()
    try:
        from trading_tom.config import settings
        logger.info("Starting daily backfill job")
        backfill(session, tickers=settings.watchlist_tickers)
        logger.info("Daily backfill complete")
    except Exception as exc:
        logger.error("Backfill job error: %s", exc)
    finally:
        session.close()


def main():
    """Entry point: start APScheduler with all jobs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Trading Tom engine starting...")

    scheduler = BlockingScheduler(timezone="America/New_York")

    # Intraday tick: every 1 min
    scheduler.add_job(
        intraday_tick,
        IntervalTrigger(minutes=1),
        id="intraday_tick",
        name="Intraday tick (day strategy)",
        max_instances=1,
        coalesce=True,
    )

    # Daily close: 16:05 ET Mon–Fri
    scheduler.add_job(
        daily_close_tick,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone="America/New_York"),
        id="daily_close_tick",
        name="Daily close tick (swing/position + EOD flatten)",
        max_instances=1,
        coalesce=True,
    )

    # Heartbeat: every 30s
    scheduler.add_job(
        heartbeat,
        IntervalTrigger(seconds=30),
        id="heartbeat",
        name="Engine heartbeat",
        max_instances=1,
        coalesce=True,
    )

    # Daily backfill: 6 AM ET Mon–Fri
    scheduler.add_job(
        daily_backfill_job,
        CronTrigger(day_of_week="mon-fri", hour=6, minute=0, timezone="America/New_York"),
        id="daily_backfill",
        name="Daily data backfill",
        max_instances=1,
        coalesce=True,
    )

    logger.info("Scheduler started. Jobs: %s", [j.name for j in scheduler.get_jobs()])
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Engine stopping.")


if __name__ == "__main__":
    main()

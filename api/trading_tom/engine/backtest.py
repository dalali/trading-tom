"""
Backtest runner — replays a strategy bar-by-bar over cached price data.

Fill model: next-bar open (Q-1 per architecture §3.5) — strategy sees bar t,
fills at open of bar t+1. Day strategy EOD flatten uses last bar's close.

The runner is constructed with a DataMode; the optimizer hardwires DEVELOPMENT
and cannot pass FINAL_EVALUATION. A separate final_evaluation() function handles
test-split runs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from trading_tom.data.repository import BarRepository, DataMode, Bar
from trading_tom.engine.base import AccountView, MarketContext, PositionView, Signal
from trading_tom.engine.executor import execute_signal, InsufficientFundsError
from trading_tom.engine.lifecycle import bust_check_and_recycle
from trading_tom.engine.metrics import Metrics, compute_metrics
from trading_tom.models.account import Account, Position
from trading_tom.models.backtest import BacktestRun

if TYPE_CHECKING:
    from trading_tom.engine.base import Strategy

logger = logging.getLogger(__name__)


def _build_account_view(session: Session, account: Account, latest_prices: dict[str, int]) -> AccountView:
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


def run_backtest(
    session: Session,
    strategy: "Strategy",
    params: dict,
    symbols: list[str],
    data_split: str,
    mode: DataMode,
    seed: int = 42,
    final_evaluation: bool = False,
    starting_capital_cents: int = 1_000_000,
) -> BacktestRun:
    """
    Bar-by-bar backtest replay.

    Returns a BacktestRun row (not yet committed — caller commits).
    Raises SplitAccessError if mode/split combination is invalid.
    """
    repo = BarRepository(session, mode)

    # Fetch bars per symbol
    all_bars: dict[str, list[Bar]] = {}
    for symbol in symbols:
        bars = repo.get_bars(symbol, "1d", splits={data_split})
        all_bars[symbol] = bars

    if not all_bars or not any(all_bars.values()):
        raise ValueError(f"No bars found for symbols {symbols} in split {data_split}")

    # Determine common timeline (all timestamps across all symbols, sorted)
    all_ts = sorted(set(
        bar.ts for bars in all_bars.values() for bar in bars
    ))
    if len(all_ts) < 2:
        raise ValueError("Not enough bars for backtest (need at least 2)")

    # Create a temporary in-session account (not persisted)
    account = Account(
        status="active",
        created_at=datetime.now(timezone.utc),
        starting_capital_cents=starting_capital_cents,
        cash_cents=starting_capital_cents,
    )
    session.add(account)
    session.flush()

    equity_series: list[int] = []
    closing_pnl: list[int] = []
    total_fees = 0
    period_start = all_ts[0]
    period_end = all_ts[-1]

    # Build bar lookup: ts → {symbol: bar}
    bar_index: dict[datetime, dict[str, Bar]] = {}
    for symbol, bars in all_bars.items():
        for bar in bars:
            bar_index.setdefault(bar.ts, {})[symbol] = bar

    required_history = strategy.required_history()

    for i, ts in enumerate(all_ts[:-1]):  # stop one before last (need next-bar for fill)
        # Bars visible to the strategy up to ts (inclusive)
        visible: dict[str, list[Bar]] = {}
        for symbol in symbols:
            visible[symbol] = [
                b for b in all_bars[symbol] if b.ts <= ts
            ][-required_history - 1:]

        latest_prices = {
            symbol: bars[-1].close_cents
            for symbol, bars in visible.items()
            if bars
        }

        ctx = MarketContext(
            as_of=ts,
            bars=visible,
            latest_prices=latest_prices,
        )

        account_view = _build_account_view(session, account, latest_prices)
        equity_series.append(account_view.equity_cents)

        try:
            signals = strategy.generate_signals(ctx, account_view, params)
        except Exception as exc:
            logger.warning("Strategy error at %s: %s", ts, exc)
            continue

        # Next bar open price for fills
        next_ts = all_ts[i + 1]
        next_bar_map = bar_index.get(next_ts, {})

        for signal in signals:
            fill_price = next_bar_map.get(signal.symbol)
            if fill_price is None:
                continue
            try:
                trade = execute_signal(
                    session, signal, account,
                    fill_price_cents=fill_price.open_cents,
                    data_split=data_split,
                    executed_at=next_ts,
                )
                total_fees += trade.fee_cents
                if trade.realized_pnl_cents is not None:
                    closing_pnl.append(trade.realized_pnl_cents)
            except InsufficientFundsError as e:
                logger.debug("Skipped signal: %s", e)
            except Exception as e:
                logger.warning("Executor error: %s", e)

        # Bust check after each bar
        account = bust_check_and_recycle(session, account, latest_prices, data_split=data_split)

    # Final equity
    final_prices = {
        symbol: all_bars[symbol][-1].close_cents
        for symbol in symbols
        if all_bars.get(symbol)
    }
    account_view = _build_account_view(session, account, final_prices)
    equity_series.append(account_view.equity_cents)

    metrics = compute_metrics(
        equity_series=equity_series,
        closing_trades_pnl=closing_pnl,
        total_fees_cents=total_fees,
        starting_capital_cents=starting_capital_cents,
    )

    run = BacktestRun(
        strategy_name=strategy.name,
        params=params,
        data_split=data_split,
        symbols=symbols,
        period_start=period_start,
        period_end=period_end,
        seed=seed,
        metrics={
            "total_return": metrics.total_return,
            "win_rate": metrics.win_rate,
            "max_drawdown": metrics.max_drawdown,
            "sharpe": metrics.sharpe,
            "n_trades": metrics.n_trades,
            "gross_pnl_cents": metrics.gross_pnl_cents,
            "net_pnl_cents": metrics.net_pnl_cents,
            "fees_cents": metrics.fees_cents,
        },
        final_evaluation=final_evaluation,
    )
    session.add(run)
    return run


def run_optimizer(
    session: Session,
    strategy: "Strategy",
    param_grid: dict[str, list],
    symbols: list[str],
    train_split: str = "train",
    val_split: str = "validation",
    seed: int = 42,
) -> tuple[dict, Metrics]:
    """
    Grid-search over param_grid using train split for fitting and validation for scoring.
    Hard-wired to DEVELOPMENT mode — cannot touch test split (C3).

    Returns (best_params, best_metrics).
    """
    # Hard-wire DEVELOPMENT; the optimizer constructor cannot accept FINAL_EVALUATION
    mode = DataMode.DEVELOPMENT

    import itertools
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = list(itertools.product(*values))

    best_params: dict = {}
    best_sharpe: float = float("-inf")
    best_metrics: Metrics | None = None

    for combo in combinations:
        params = dict(zip(keys, combo))
        try:
            run = run_backtest(
                session, strategy, params, symbols,
                data_split=val_split,
                mode=mode,
                seed=seed,
            )
            sharpe = run.metrics.get("sharpe", 0.0)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = params
                from trading_tom.engine.metrics import Metrics
                best_metrics = Metrics(
                    total_return=run.metrics["total_return"],
                    win_rate=run.metrics["win_rate"],
                    max_drawdown=run.metrics["max_drawdown"],
                    sharpe=run.metrics["sharpe"],
                    n_trades=run.metrics["n_trades"],
                    gross_pnl_cents=run.metrics["gross_pnl_cents"],
                    net_pnl_cents=run.metrics["net_pnl_cents"],
                    fees_cents=run.metrics["fees_cents"],
                )
            session.rollback()  # don't persist intermediate runs
        except Exception as exc:
            logger.warning("Optimizer error with params %s: %s", params, exc)
            session.rollback()

    return best_params, best_metrics


def final_evaluation(
    session: Session,
    strategy: "Strategy",
    params: dict,
    symbols: list[str],
    seed: int = 42,
    confirm: bool = False,
) -> BacktestRun:
    """
    Honest out-of-sample evaluation on the test split.
    Requires explicit confirm=True to prevent accidental calls.
    Records final_evaluation=True on the run (architecture §4.3).
    """
    if not confirm:
        raise ValueError(
            "final_evaluation() requires confirm=True. "
            "This runs against the held-out test split — use sparingly."
        )

    run = run_backtest(
        session, strategy, params, symbols,
        data_split="test",
        mode=DataMode.FINAL_EVALUATION,
        seed=seed,
        final_evaluation=True,
    )
    session.commit()
    logger.info(
        "Final evaluation complete: strategy=%s return=%.2f%% sharpe=%.2f",
        strategy.name,
        run.metrics.get("total_return", 0) * 100,
        run.metrics.get("sharpe", 0),
    )
    return run

"""Performance metrics computed from a list of trades and equity series."""
from __future__ import annotations

import math
from typing import NamedTuple


class Metrics(NamedTuple):
    total_return: float          # (final - initial) / initial
    win_rate: float              # fraction of closing trades with realized_pnl > 0
    max_drawdown: float          # maximum peak-to-trough drop (as negative fraction)
    sharpe: float                # annualized Sharpe ratio (daily returns, rf=0)
    n_trades: int
    gross_pnl_cents: int
    net_pnl_cents: int
    fees_cents: int


def compute_metrics(
    equity_series: list[int],      # equity_cents at each bar (length = n_bars)
    closing_trades_pnl: list[int], # realized_pnl_cents for each closing trade
    total_fees_cents: int,
    starting_capital_cents: int,
) -> Metrics:
    """
    Compute standard backtest metrics.

    equity_series: list of equity values (one per bar) — used for drawdown + Sharpe
    closing_trades_pnl: realized P&L per closed trade (net of fees) — for win rate
    total_fees_cents: sum of all fee_cents in the run
    starting_capital_cents: initial equity
    """
    n_trades = len(closing_trades_pnl)
    gross_pnl_cents = sum(closing_trades_pnl)  # includes fee impact since pnl is net
    net_pnl_cents = gross_pnl_cents  # already net; gross would need separate tracking

    # Total return
    final = equity_series[-1] if equity_series else starting_capital_cents
    total_return = (final - starting_capital_cents) / starting_capital_cents if starting_capital_cents else 0.0

    # Win rate
    wins = sum(1 for p in closing_trades_pnl if p > 0)
    win_rate = wins / n_trades if n_trades > 0 else 0.0

    # Max drawdown (peak-to-trough)
    max_drawdown = 0.0
    if equity_series:
        peak = equity_series[0]
        for eq in equity_series:
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak if peak > 0 else 0.0
            if dd < max_drawdown:
                max_drawdown = dd

    # Sharpe ratio (annualized, daily, rf=0)
    sharpe = 0.0
    if len(equity_series) > 1:
        daily_returns = [
            (equity_series[i] - equity_series[i - 1]) / equity_series[i - 1]
            for i in range(1, len(equity_series))
            if equity_series[i - 1] > 0
        ]
        if daily_returns:
            mean_r = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            std_r = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    return Metrics(
        total_return=total_return,
        win_rate=win_rate,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        n_trades=n_trades,
        gross_pnl_cents=gross_pnl_cents,
        net_pnl_cents=net_pnl_cents,
        fees_cents=total_fees_cents,
    )

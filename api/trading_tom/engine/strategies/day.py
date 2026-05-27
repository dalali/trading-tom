"""
Day trading strategy: intraday MA crossover.

Logic:
  - Fast/slow moving average crossover on 1m bars.
  - Enter long (buy) on bullish cross (fast crosses above slow).
  - Exit long (sell) on bearish cross (fast crosses below slow).
  - Flat by close: any open day position is force-sold at last bar.

Parameters (from strategy_configs.params):
  fast_ma: int = 9
  slow_ma: int = 21
  position_size_pct: float = 0.05  (fraction of equity per position)
  max_positions: int = 3
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from trading_tom.engine.base import AccountView, MarketContext, Signal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

NAME = "day"


def _sma(prices: list[int], window: int) -> float | None:
    if len(prices) < window:
        return None
    return float(np.mean(prices[-window:]))


def _compute_quantity(
    equity_cents: int,
    price_cents: int,
    position_size_pct: float,
    max_positions: int,
    current_positions: int,
) -> int:
    """Fixed fractional sizing: floor(equity * pct / price), capped by max_positions."""
    if current_positions >= max_positions or price_cents <= 0:
        return 0
    target_value = equity_cents * position_size_pct / max_positions
    return max(0, int(target_value / price_cents))


class DayMACrossStrategy:
    name = NAME

    def required_history(self) -> int:
        return 21  # enough for the slow MA default

    def generate_signals(
        self,
        ctx: MarketContext,
        account: AccountView,
        params: dict,
    ) -> list[Signal]:
        fast_ma = int(params.get("fast_ma", 9))
        slow_ma = int(params.get("slow_ma", 21))
        position_size_pct = float(params.get("position_size_pct", 0.05))
        max_positions = int(params.get("max_positions", 3))

        signals: list[Signal] = []
        watchlist = list(ctx.bars.keys())

        for symbol in watchlist:
            bars = ctx.get_bars(symbol)
            if len(bars) < slow_ma + 1:
                continue  # not enough history

            closes = [b.close_cents for b in bars]

            fast_now = _sma(closes, fast_ma)
            fast_prev = _sma(closes[:-1], fast_ma)
            slow_now = _sma(closes, slow_ma)
            slow_prev = _sma(closes[:-1], slow_ma)

            if None in (fast_now, fast_prev, slow_now, slow_prev):
                continue

            pos = account.get_position(symbol)
            current_open_count = len([p for p in account.open_positions if p.quantity > 0])

            # Bullish cross: fast crosses above slow
            if fast_prev <= slow_prev and fast_now > slow_now and pos is None:
                price = ctx.latest_price(symbol)
                if price is None:
                    continue
                qty = _compute_quantity(
                    account.equity_cents, price,
                    position_size_pct, max_positions, current_open_count
                )
                if qty > 0:
                    signals.append(Signal(
                        symbol=symbol,
                        side="buy",
                        quantity=qty,
                        reason=f"{NAME}:bullish_cross fast={fast_ma} slow={slow_ma}",
                    ))

            # Bearish cross: fast crosses below slow — exit any open position
            elif fast_prev >= slow_prev and fast_now < slow_now and pos is not None and pos.quantity > 0:
                signals.append(Signal(
                    symbol=symbol,
                    side="sell",
                    quantity=pos.quantity,
                    reason=f"{NAME}:bearish_cross",
                ))

        return signals

    def generate_eod_flatten_signals(
        self, account: AccountView, strategy_name: str = NAME
    ) -> list[Signal]:
        """Force-sell all open day positions at end of session."""
        signals = []
        for pos in account.open_positions:
            if pos.quantity > 0:
                signals.append(Signal(
                    symbol=pos.symbol,
                    side="sell",
                    quantity=pos.quantity,
                    reason=f"{strategy_name}:eod_flatten",
                ))
        return signals

"""
Position trading strategy: 50/200 SMA golden/death cross.

Logic:
  - Buy when 50-day SMA crosses above 200-day SMA (golden cross).
  - Sell when 50-day SMA crosses below 200-day SMA (death cross).
  - Holds for weeks to months.

Parameters (from strategy_configs.params):
  sma_fast: int = 50
  sma_slow: int = 200
  position_size_pct: float = 0.20
  max_positions: int = 5
"""
from __future__ import annotations

import logging

import numpy as np

from trading_tom.engine.base import AccountView, MarketContext, Signal

logger = logging.getLogger(__name__)

NAME = "position"


def _sma(prices: list[int], window: int) -> float | None:
    if len(prices) < window:
        return None
    return float(np.mean(prices[-window:]))


def _compute_quantity(equity_cents: int, price_cents: int, position_size_pct: float) -> int:
    if price_cents <= 0:
        return 0
    return max(0, int(equity_cents * position_size_pct / price_cents))


class PositionGoldenCrossStrategy:
    name = NAME

    def required_history(self) -> int:
        return 201  # 200-day SMA + 1 prev bar for crossover detection

    def generate_signals(
        self,
        ctx: MarketContext,
        account: AccountView,
        params: dict,
    ) -> list[Signal]:
        sma_fast = int(params.get("sma_fast", 50))
        sma_slow = int(params.get("sma_slow", 200))
        position_size_pct = float(params.get("position_size_pct", 0.20))
        max_positions = int(params.get("max_positions", 5))

        signals: list[Signal] = []
        open_count = sum(1 for p in account.open_positions if p.quantity > 0)

        for symbol, bars in ctx.bars.items():
            if len(bars) < sma_slow + 1:
                continue

            closes = [b.close_cents for b in bars]
            fast_now = _sma(closes, sma_fast)
            fast_prev = _sma(closes[:-1], sma_fast)
            slow_now = _sma(closes, sma_slow)
            slow_prev = _sma(closes[:-1], sma_slow)

            if None in (fast_now, fast_prev, slow_now, slow_prev):
                continue

            pos = account.get_position(symbol)
            latest_price = ctx.latest_price(symbol)

            # Golden cross: fast crosses above slow → buy
            if (
                fast_prev <= slow_prev
                and fast_now > slow_now
                and pos is None
                and open_count < max_positions
                and latest_price is not None
            ):
                qty = _compute_quantity(account.equity_cents, latest_price, position_size_pct)
                if qty > 0:
                    signals.append(Signal(
                        symbol=symbol,
                        side="buy",
                        quantity=qty,
                        reason=f"{NAME}:golden_cross sma{sma_fast}>{sma_slow}",
                    ))
                    open_count += 1

            # Death cross: fast crosses below slow → sell
            elif (
                fast_prev >= slow_prev
                and fast_now < slow_now
                and pos is not None
                and pos.quantity > 0
            ):
                signals.append(Signal(
                    symbol=symbol,
                    side="sell",
                    quantity=pos.quantity,
                    reason=f"{NAME}:death_cross sma{sma_fast}<{sma_slow}",
                ))

        return signals

"""
Swing trading strategy: RSI mean-reversion.

Logic:
  - RSI(period) on 1d bars.
  - Buy when RSI < rsi_buy AND price > sma_trend-day SMA (trend filter).
  - Sell when RSI > rsi_sell OR held for max_hold_days.

Parameters (from strategy_configs.params):
  rsi_period: int = 14
  rsi_buy: int = 30      (oversold threshold)
  rsi_sell: int = 60     (overbought threshold)
  sma_trend: int = 50    (trend filter SMA period)
  max_hold_days: int = 10
  position_size_pct: float = 0.10
  max_positions: int = 5
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone
from typing import TYPE_CHECKING

import numpy as np

from trading_tom.engine.base import AccountView, MarketContext, Signal

logger = logging.getLogger(__name__)

NAME = "swing"


def _rsi(closes: list[int], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = diffs[-period:]
    gains = [d for d in recent if d > 0]
    losses = [abs(d) for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _sma(prices: list[int], window: int) -> float | None:
    if len(prices) < window:
        return None
    return float(np.mean(prices[-window:]))


def _compute_quantity(equity_cents: int, price_cents: int, position_size_pct: float) -> int:
    if price_cents <= 0:
        return 0
    return max(0, int(equity_cents * position_size_pct / price_cents))


class SwingRSIStrategy:
    name = NAME

    def required_history(self) -> int:
        return 65  # enough for RSI(14) + SMA(50)

    def generate_signals(
        self,
        ctx: MarketContext,
        account: AccountView,
        params: dict,
    ) -> list[Signal]:
        rsi_period = int(params.get("rsi_period", 14))
        rsi_buy = float(params.get("rsi_buy", 30))
        rsi_sell = float(params.get("rsi_sell", 60))
        sma_trend = int(params.get("sma_trend", 50))
        max_hold_days = int(params.get("max_hold_days", 10))
        position_size_pct = float(params.get("position_size_pct", 0.10))
        max_positions = int(params.get("max_positions", 5))

        signals: list[Signal] = []
        open_count = sum(1 for p in account.open_positions if p.quantity > 0)

        for symbol, bars in ctx.bars.items():
            if not bars:
                continue
            closes = [b.close_cents for b in bars]

            rsi_val = _rsi(closes, rsi_period)
            sma_val = _sma(closes, sma_trend)
            latest_price = ctx.latest_price(symbol)

            if rsi_val is None or sma_val is None or latest_price is None:
                continue

            pos = account.get_position(symbol)

            # Entry: RSI oversold + above trend SMA
            if (
                rsi_val < rsi_buy
                and latest_price > sma_val
                and pos is None
                and open_count < max_positions
            ):
                qty = _compute_quantity(account.equity_cents, latest_price, position_size_pct)
                if qty > 0:
                    signals.append(Signal(
                        symbol=symbol,
                        side="buy",
                        quantity=qty,
                        reason=f"{NAME}:rsi_oversold rsi={rsi_val:.1f}",
                    ))
                    open_count += 1

            # Exit: RSI overbought or max hold exceeded
            elif pos is not None and pos.quantity > 0:
                # Check hold duration (use bar timestamps as proxy)
                entry_approx = bars[-1].ts - timedelta(days=max_hold_days)
                max_hold_exceeded = bars[0].ts < entry_approx  # rough check

                if rsi_val > rsi_sell or max_hold_exceeded:
                    reason = "rsi_overbought" if rsi_val > rsi_sell else "max_hold_exceeded"
                    signals.append(Signal(
                        symbol=symbol,
                        side="sell",
                        quantity=pos.quantity,
                        reason=f"{NAME}:{reason}",
                    ))

        return signals

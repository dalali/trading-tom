"""
Swing trading strategy: Double RSI mean-reversion with volume confirmation.

Logic:
  - RSI(14) < rsi_buy AND RSI(2) < rsi2_entry AND volume > vol_period-day avg * vol_mult.
  - Sell when RSI(14) > rsi_sell OR held for max_hold_days OR stop-loss hit.

Parameters (from strategy_configs.params):
  rsi_period: int = 14
  rsi_buy: int = 30        (RSI-14 oversold threshold)
  rsi_sell: int = 75       (RSI-14 overbought exit)
  rsi2_entry: int = 20     (RSI-2 further confirmation)
  vol_period: int = 10     (volume SMA window for confirmation)
  vol_mult: float = 1.5    (required volume multiple vs avg)
  max_hold_days: int = 10
  position_size_pct: float = 0.25
  max_positions: int = 3
  stop_loss_pct: float = 0.05
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
        return 30  # enough for RSI(14) + vol_period(10)

    def generate_signals(
        self,
        ctx: MarketContext,
        account: AccountView,
        params: dict,
    ) -> list[Signal]:
        rsi_period = int(params.get("rsi_period", 14))
        rsi_buy = float(params.get("rsi_buy", 30))
        rsi_sell = float(params.get("rsi_sell", 75))
        rsi2_entry = float(params.get("rsi2_entry", 20))
        vol_period = int(params.get("vol_period", 10))
        vol_mult = float(params.get("vol_mult", 1.5))
        max_hold_days = int(params.get("max_hold_days", 10))
        position_size_pct = float(params.get("position_size_pct", 0.25))
        max_positions = int(params.get("max_positions", 3))
        stop_loss_pct = float(params.get("stop_loss_pct", 0.05))

        signals: list[Signal] = []
        open_count = sum(1 for p in account.open_positions if p.quantity > 0)

        for symbol, bars in ctx.bars.items():
            if not bars:
                continue
            closes = [b.close_cents for b in bars]
            volumes = [b.volume for b in bars]

            rsi_val = _rsi(closes, rsi_period)
            rsi2_val = _rsi(closes, 2)
            vol_avg = _sma(volumes, vol_period)
            latest_price = ctx.latest_price(symbol)
            current_vol = volumes[-1] if volumes else 0

            if rsi_val is None or latest_price is None:
                continue

            vol_confirmed = vol_avg is None or (vol_avg > 0 and current_vol >= vol_avg * vol_mult)
            rsi2_confirmed = rsi2_val is None or rsi2_val < rsi2_entry

            pos = account.get_position(symbol)

            # Entry: RSI(14) oversold + RSI(2) confirms + volume spike
            if (
                rsi_val < rsi_buy
                and rsi2_confirmed
                and vol_confirmed
                and pos is None
                and open_count < max_positions
            ):
                qty = _compute_quantity(account.equity_cents, latest_price, position_size_pct)
                if qty > 0:
                    rsi2_str = f" rsi2={rsi2_val:.1f}" if rsi2_val is not None else ""
                    signals.append(Signal(
                        symbol=symbol,
                        side="buy",
                        quantity=qty,
                        reason=f"{NAME}:rsi_oversold rsi={rsi_val:.1f}{rsi2_str} vol={current_vol/(vol_avg or 1):.1f}x",
                    ))
                    open_count += 1

            # Exit: RSI overbought or max hold exceeded
            elif pos is not None and pos.quantity > 0:
                # Check hold duration (use bar timestamps as proxy)
                entry_approx = bars[-1].ts - timedelta(days=max_hold_days)
                max_hold_exceeded = bars[0].ts < entry_approx  # rough check

                stop_hit = latest_price < pos.avg_entry_price_cents * (1 - stop_loss_pct)
                if rsi_val > rsi_sell or max_hold_exceeded or stop_hit:
                    if stop_hit:
                        reason = "stop_loss"
                    elif rsi_val > rsi_sell:
                        reason = "rsi_overbought"
                    else:
                        reason = "max_hold_exceeded"
                    signals.append(Signal(
                        symbol=symbol,
                        side="sell",
                        quantity=pos.quantity,
                        reason=f"{NAME}:{reason}",
                    ))

        return signals

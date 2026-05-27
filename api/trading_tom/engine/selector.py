"""
Strategy selector: picks active strategy set based on market regime.

Regime rules (deterministic, logged each day):
  - Compute 20-day realized volatility and 50/200 SMA trend on proxy (SPY).
  - Strong uptrend (50>200 SMA) & low vol → position + swing enabled.
  - Range/mean-revert (no clear SMA trend) & moderate vol → swing.
  - High vol → day (intraday) favored; longer-horizon entries paused.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from trading_tom.engine.strategies.day import DayMACrossStrategy
from trading_tom.engine.strategies.swing import SwingRSIStrategy
from trading_tom.engine.strategies.position import PositionGoldenCrossStrategy

if TYPE_CHECKING:
    from trading_tom.engine.base import MarketContext

logger = logging.getLogger(__name__)

PROXY = "SPY"

# Volatility thresholds (annualized, approximate)
HIGH_VOL_THRESHOLD = 0.25   # > 25% annualized daily vol = high vol regime
LOW_VOL_THRESHOLD = 0.12    # < 12% = low vol regime

_ALL_STRATEGIES = [
    DayMACrossStrategy(),
    SwingRSIStrategy(),
    PositionGoldenCrossStrategy(),
]
_STRATEGY_MAP = {s.name: s for s in _ALL_STRATEGIES}


def _realized_vol_20d(closes: list[int]) -> float:
    """20-day realized volatility (annualized) from daily close prices."""
    if len(closes) < 21:
        return 0.15  # default moderate
    log_returns = [
        np.log(closes[i] / closes[i - 1])
        for i in range(max(1, len(closes) - 20), len(closes))
        if closes[i - 1] > 0
    ]
    if not log_returns:
        return 0.15
    return float(np.std(log_returns) * np.sqrt(252))


def _sma(prices: list[int], window: int) -> float | None:
    if len(prices) < window:
        return None
    return float(np.mean(prices[-window:]))


def select_strategies(
    ctx: "MarketContext",
    enabled_names: set[str],
) -> list:
    """
    Return the list of strategy instances to run for the current bar.

    Args:
        ctx: current market context
        enabled_names: set of strategy names that are enabled in strategy_configs
    """
    spy_bars = ctx.get_bars(PROXY)

    if not spy_bars or len(spy_bars) < 21:
        # No proxy data — run all enabled strategies
        logger.warning("No SPY data for regime detection; enabling all strategies")
        result = [s for s in _ALL_STRATEGIES if s.name in enabled_names]
        logger.info("Regime: unknown → strategies: %s", [s.name for s in result])
        return result

    closes = [b.close_cents for b in spy_bars]
    vol = _realized_vol_20d(closes)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)

    # Determine regime
    if vol > HIGH_VOL_THRESHOLD:
        regime = "high_vol"
        active = {"day"}
    elif sma50 is not None and sma200 is not None and sma50 > sma200:
        regime = "uptrend_low_vol" if vol <= LOW_VOL_THRESHOLD else "uptrend_mod_vol"
        active = {"position", "swing"}
    else:
        regime = "range_bound"
        active = {"swing"}

    # Intersect with enabled strategies
    selected = [
        _STRATEGY_MAP[name]
        for name in active
        if name in enabled_names and name in _STRATEGY_MAP
    ]

    logger.info(
        "Regime: %s (vol=%.3f sma50=%s sma200=%s) → strategies: %s",
        regime,
        vol,
        f"{sma50:.0f}" if sma50 else "N/A",
        f"{sma200:.0f}" if sma200 else "N/A",
        [s.name for s in selected],
    )
    return selected

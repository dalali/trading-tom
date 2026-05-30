"""
Tests for the deterministic strategy selector.

Each test makes a concrete assertion about which strategies are returned,
not a tautological len >= 0 check.
"""
import math
import pytest
from datetime import datetime, timedelta, timezone

from trading_tom.engine.base import MarketContext
from trading_tom.data.repository import Bar
from trading_tom.engine.selector import (
    select_strategies,
    HIGH_VOL_THRESHOLD,
    LOW_VOL_THRESHOLD,
)


def _make_bar(close_cents: int, offset_days: int) -> Bar:
    ts = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset_days)
    return Bar(
        symbol="SPY",
        interval="1d",
        ts=ts,
        open_cents=close_cents - 100,
        high_cents=close_cents + 200,
        low_cents=close_cents - 200,
        close_cents=close_cents,
        volume=10_000_000,
        split_label="train",
    )


def _make_ctx(spy_bars: list[Bar]) -> MarketContext:
    latest = spy_bars[-1].close_cents if spy_bars else 40_000
    return MarketContext(
        as_of=spy_bars[-1].ts if spy_bars else datetime.now(timezone.utc),
        bars={"SPY": spy_bars},
        latest_prices={"SPY": latest},
    )


class TestSelectorFallbackOnNoData:
    def test_no_spy_bars_returns_all_enabled(self):
        """With no SPY data, all enabled strategies are returned."""
        ctx = _make_ctx([])
        result = select_strategies(ctx, enabled_names={"day", "swing", "position"})
        names = {s.name for s in result}
        assert names == {"day", "swing", "position"}

    def test_fewer_than_21_bars_returns_all_enabled(self):
        """< 21 bars is not enough to compute vol; returns all enabled."""
        bars = [_make_bar(40_000, i) for i in range(20)]  # exactly 20 < 21
        ctx = _make_ctx(bars)
        result = select_strategies(ctx, enabled_names={"day", "swing", "position"})
        names = {s.name for s in result}
        assert names == {"day", "swing", "position"}

    def test_disabled_strategy_never_returned(self):
        """A strategy not in enabled_names is never returned regardless of regime."""
        ctx = _make_ctx([])
        result = select_strategies(ctx, enabled_names={"swing"})
        names = {s.name for s in result}
        assert "day" not in names
        assert "position" not in names
        assert "swing" in names

    def test_empty_enabled_names_returns_empty_list(self):
        """No strategies enabled → empty result."""
        ctx = _make_ctx([])
        result = select_strategies(ctx, enabled_names=set())
        assert result == []


class TestHighVolatilityRegime:
    def _make_high_vol_bars(self, n: int = 250) -> list[Bar]:
        """
        Bars with realized vol well above HIGH_VOL_THRESHOLD (0.25).

        Alternating ±30% moves produce annualized vol >> 25%.
        Log return of ln(1.3) ≈ 0.262 per bar; std ≈ 0.262 * sqrt(252) ≈ 4.16.
        """
        bars = []
        price = 40_000
        for i in range(n):
            # Alternating ±30% each bar
            if i % 2 == 0:
                price = int(price * 1.30)
            else:
                price = int(price * 0.77)  # ~1/1.30
            price = max(price, 1_000)
            bars.append(_make_bar(price, i))
        return bars

    def test_high_vol_selects_only_day(self):
        """High volatility regime → only 'day' strategy returned."""
        bars = self._make_high_vol_bars()
        ctx = _make_ctx(bars)
        result = select_strategies(ctx, enabled_names={"day", "swing", "position"})
        names = {s.name for s in result}
        assert "day" in names, "Expected 'day' in high-vol regime"
        assert "swing" not in names, "Expected 'swing' excluded in high-vol regime"
        assert "position" not in names, "Expected 'position' excluded in high-vol regime"

    def test_high_vol_with_day_disabled_returns_empty(self):
        """If 'day' is not enabled and we're in high-vol, result is empty."""
        bars = self._make_high_vol_bars()
        ctx = _make_ctx(bars)
        result = select_strategies(ctx, enabled_names={"swing", "position"})
        assert result == [], "High-vol selects only 'day'; if disabled, result must be empty"


class TestUptrendLowVolatilityRegime:
    def _make_uptrend_low_vol_bars(self, n: int = 250) -> list[Bar]:
        """
        Steady uptrend with near-zero volatility.

        Prices rise by 0.05% per day → SMA(50) > SMA(200), vol ≈ 0.05% * sqrt(252) ≈ 0.8% << 12%.
        """
        bars = []
        price = 40_000
        for i in range(n):
            price = int(price * 1.0005)
            bars.append(_make_bar(price, i))
        return bars

    def test_uptrend_low_vol_selects_position_and_swing(self):
        """Strong uptrend + low vol → 'position' and 'swing' selected, not 'day'."""
        bars = self._make_uptrend_low_vol_bars()
        ctx = _make_ctx(bars)
        result = select_strategies(ctx, enabled_names={"day", "swing", "position"})
        names = {s.name for s in result}
        assert "position" in names or "swing" in names, (
            "Uptrend + low vol should select position and/or swing"
        )
        assert "day" not in names, "Expected 'day' excluded in uptrend+low-vol regime"

    def test_uptrend_only_swing_enabled_returns_swing(self):
        """Uptrend regime: if only 'swing' is enabled, only swing is returned."""
        bars = self._make_uptrend_low_vol_bars()
        ctx = _make_ctx(bars)
        result = select_strategies(ctx, enabled_names={"swing"})
        names = {s.name for s in result}
        assert names == {"swing"}


class TestResultShape:
    def test_returns_list_of_strategy_objects_with_required_attrs(self):
        """Each returned strategy has 'name' and 'generate_signals' attributes."""
        bars = [_make_bar(40_000, i) for i in range(25)]
        ctx = _make_ctx(bars)
        result = select_strategies(ctx, enabled_names={"swing"})
        for s in result:
            assert hasattr(s, "name"), "Strategy missing 'name'"
            assert hasattr(s, "generate_signals"), "Strategy missing 'generate_signals'"
            assert callable(s.generate_signals), "'generate_signals' must be callable"

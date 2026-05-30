"""
Strategy behavioral tests — each test asserts a concrete signal outcome,
not just "returns a list".
"""
import pytest
from datetime import datetime, timedelta, timezone

from trading_tom.engine.base import AccountView, MarketContext, PositionView
from trading_tom.data.repository import Bar
from trading_tom.engine.strategies.day import DayMACrossStrategy
from trading_tom.engine.strategies.swing import SwingRSIStrategy
from trading_tom.engine.strategies.position import PositionGoldenCrossStrategy


def _make_bar(symbol: str, close_cents: int, offset_days: int, interval: str = "1d") -> Bar:
    ts = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset_days)
    return Bar(
        symbol=symbol,
        interval=interval,
        ts=ts,
        open_cents=close_cents - 100,
        high_cents=close_cents + 200,
        low_cents=close_cents - 200,
        close_cents=close_cents,
        volume=1_000_000,
        split_label="train",
    )


def _make_account(cash_cents: int = 1_000_000, positions=None) -> AccountView:
    return AccountView(
        account_id=1,
        cash_cents=cash_cents,
        equity_cents=cash_cents,
        open_positions=positions or [],
    )


class TestDayMACrossStrategy:
    def _make_crossover_bars(self, fast_ma: int = 5, slow_ma: int = 10) -> list[Bar]:
        """
        Build bars where the bullish MA crossover fires on the LAST bar.

        Phase 1 (bars 0..slow_ma+fast_ma+1): flat at 100 cents.
        The last bar surges to 200 cents, which is enough to push
        fast MA above slow MA while keeping price affordable.

        Verified:
          fast_prev (100) <= slow_prev (100) ✓
          fast_now  (120) > slow_now  (110) ✓  (for fast=5, slow=10)
          qty = int(1_000_000 * 0.10 / 200) = 500 > 0 ✓

        Strategy checks len(bars) >= slow_ma + 1; we provide slow_ma + fast_ma + 3 bars.
        """
        flat_bars = slow_ma + fast_ma + 2
        bars = [_make_bar("AAPL", 100, i, interval="1m") for i in range(flat_bars)]
        # Surge to 200: lifts fast MA above slow MA (proof: for fast=5, slow=10:
        # fast_now = (4*100+200)/5=120, fast_prev=100; slow_now=(9*100+200)/10=110, slow_prev=100)
        bars.append(_make_bar("AAPL", 200, flat_bars, interval="1m"))
        return bars

    def test_bullish_cross_generates_buy_with_qty(self):
        """Bullish MA crossover on last bar → BUY signal with qty > 0."""
        fast_ma, slow_ma = 5, 10
        bars = self._make_crossover_bars(fast_ma=fast_ma, slow_ma=slow_ma)
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"AAPL": bars},
            latest_prices={"AAPL": bars[-1].close_cents},
        )
        account = _make_account(cash_cents=1_000_000)
        strategy = DayMACrossStrategy()
        params = {
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "position_size_pct": 0.10,
            "max_positions": 3,
        }
        signals = strategy.generate_signals(ctx, account, params)
        buy_signals = [s for s in signals if s.side == "buy" and s.symbol == "AAPL"]
        assert len(buy_signals) == 1, f"Expected 1 BUY signal, got {signals}"
        assert buy_signals[0].quantity > 0

    def test_no_signal_when_insufficient_history(self):
        """Fewer bars than slow_ma → no signal."""
        bars = [_make_bar("AAPL", 10_000, i, interval="1m") for i in range(5)]
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"AAPL": bars},
            latest_prices={"AAPL": bars[-1].close_cents},
        )
        account = _make_account()
        strategy = DayMACrossStrategy()
        params = {"fast_ma": 9, "slow_ma": 21, "position_size_pct": 0.05, "max_positions": 3}
        signals = strategy.generate_signals(ctx, account, params)
        assert signals == []

    def test_no_buy_when_position_already_held(self):
        """Bullish cross on last bar but position already open → no BUY."""
        fast_ma, slow_ma = 5, 10
        bars = self._make_crossover_bars(fast_ma=fast_ma, slow_ma=slow_ma)
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"AAPL": bars},
            latest_prices={"AAPL": bars[-1].close_cents},
        )
        # Already holding AAPL
        account = _make_account(positions=[PositionView("AAPL", 5, 10_000)])
        strategy = DayMACrossStrategy()
        params = {"fast_ma": fast_ma, "slow_ma": slow_ma, "position_size_pct": 0.10, "max_positions": 3}
        signals = strategy.generate_signals(ctx, account, params)
        buy_signals = [s for s in signals if s.side == "buy" and s.symbol == "AAPL"]
        assert len(buy_signals) == 0

    def test_eod_flatten_generates_sell_for_each_position(self):
        """generate_eod_flatten_signals returns SELL for every open position."""
        strategy = DayMACrossStrategy()
        account = _make_account(
            positions=[PositionView("AAPL", 10, 18_000), PositionView("MSFT", 5, 40_000)]
        )
        signals = strategy.generate_eod_flatten_signals(account)
        assert len(signals) == 2
        sides = {s.side for s in signals}
        assert sides == {"sell"}
        symbols = {s.symbol for s in signals}
        assert symbols == {"AAPL", "MSFT"}

    def test_eod_flatten_single_position_qty_matches(self):
        """EOD flatten signal quantity equals the held quantity."""
        strategy = DayMACrossStrategy()
        account = _make_account(positions=[PositionView("AAPL", 7, 18_000)])
        signals = strategy.generate_eod_flatten_signals(account)
        assert len(signals) == 1
        assert signals[0].side == "sell"
        assert signals[0].symbol == "AAPL"
        assert signals[0].quantity == 7

    def test_eod_flatten_no_positions_returns_empty(self):
        """EOD flatten with no open positions returns empty list."""
        strategy = DayMACrossStrategy()
        account = _make_account()
        signals = strategy.generate_eod_flatten_signals(account)
        assert signals == []


class TestSwingRSIStrategy:
    PARAMS = {
        "rsi_period": 14,
        "rsi_buy": 30,
        "rsi_sell": 60,
        "sma_trend": 50,
        "max_hold_days": 10,
        "position_size_pct": 0.10,
        "max_positions": 5,
    }

    def _make_oversold_bars(self) -> list[Bar]:
        """
        Create bars where RSI < 30 on the last bar and price > SMA(50).

        50 rising bars set a high SMA(50) base.  Then 14 small drops make
        RSI drop to 0 (all losses) while price stays well above SMA(50).

        Verified:
          RSI = 0.0 < 30 ✓
          last_price (57_600) > SMA(50) (46_190) ✓
        """
        bars = []
        # 50 rising bars: 10_000 to 59_000
        for i in range(50):
            bars.append(_make_bar("MSFT", 10_000 + i * 1_000, i))
        # 14 small drops from peak: RSI → 0, price stays above SMA(50)
        peak = bars[-1].close_cents  # 59_000
        for j in range(14):
            bars.append(_make_bar("MSFT", peak - (j + 1) * 100, 50 + j))
        return bars

    def _make_overbought_bars(self) -> list[Bar]:
        """
        Create bars where RSI > 60 on the last bar.

        Steady climb for 70 bars so RSI is high.
        """
        bars = [_make_bar("TSLA", 10_000 + i * 200, i) for i in range(70)]
        return bars

    def test_rsi_oversold_generates_buy(self):
        """RSI < 30 threshold + price > SMA(50) → BUY signal."""
        bars = self._make_oversold_bars()
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"MSFT": bars},
            latest_prices={"MSFT": bars[-1].close_cents},
        )
        account = _make_account()
        strategy = SwingRSIStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        buy_signals = [s for s in signals if s.side == "buy" and s.symbol == "MSFT"]
        assert len(buy_signals) == 1
        assert buy_signals[0].quantity > 0

    def test_rsi_overbought_generates_sell_when_position_held(self):
        """RSI > 60 + holding position → SELL signal."""
        bars = self._make_overbought_bars()
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"TSLA": bars},
            latest_prices={"TSLA": bars[-1].close_cents},
        )
        pos = PositionView("TSLA", 5, 10_000)
        account = _make_account(positions=[pos])
        strategy = SwingRSIStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        sell_signals = [s for s in signals if s.side == "sell" and s.symbol == "TSLA"]
        assert len(sell_signals) == 1
        assert sell_signals[0].quantity == 5

    def test_flat_bars_produce_no_signal(self):
        """Flat price series → RSI returns 100 (no gains and no losses → RSI=100),
        which is > rsi_sell. No position held → no sell, no buy (RSI too high for buy)."""
        # All same price → no movement → RSI is 100 (avg_loss=0 branch)
        bars = [_make_bar("AAPL", 15_000, i) for i in range(70)]
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"AAPL": bars},
            latest_prices={"AAPL": bars[-1].close_cents},
        )
        account = _make_account()  # no positions
        strategy = SwingRSIStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        buy_signals = [s for s in signals if s.side == "buy"]
        assert buy_signals == [], "Flat bars (RSI=100) should not trigger a BUY"

    def test_no_buy_when_insufficient_bars_for_rsi(self):
        """Fewer bars than rsi_period + 1 → RSI is None → no signal."""
        bars = [_make_bar("MSFT", 20_000, i) for i in range(10)]  # only 10 < 15
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"MSFT": bars},
            latest_prices={"MSFT": bars[-1].close_cents},
        )
        account = _make_account()
        strategy = SwingRSIStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        assert signals == []


class TestPositionGoldenCrossStrategy:
    PARAMS = {
        "sma_fast": 50,
        "sma_slow": 200,
        "position_size_pct": 0.20,
        "max_positions": 5,
    }

    def _make_golden_cross_bars(self) -> list[Bar]:
        """
        Golden cross: SMA(50) crosses above SMA(200) on the last bar.

        Phase 1 (bars 0..199): flat at 10_000 so SMA(50) == SMA(200) == 10_000.
        Phase 2 (bars 200..249): rising so SMA(50) climbs above SMA(200).
        We need exactly the crossover on bar[-1]:
          - At bar[-2]: SMA(50)_prev <= SMA(200)_prev
          - At bar[-1]: SMA(50)_now  > SMA(200)_now

        Strategy requires len(bars) >= sma_slow + 1 = 201.
        """
        bars = []
        # 200 flat bars
        for i in range(200):
            bars.append(_make_bar("NVDA", 10_000, i))
        # 50 rising bars so SMA(50) lifts.  We need the cross at the last bar.
        # After 50 rises the SMA(50) will be well above SMA(200).
        # We want the cross exactly at bar index 200 (the 201st bar).
        # At bar 199: SMA(50) = mean of bars[150..199] = 10_000 (all flat)
        # At bar 200: add bar with high price so SMA(50) jumps.
        # SMA(200) at bar 200 = mean of bars[1..200] = (199*10_000 + surge) / 200
        # For cross: new_fast > new_slow: (199*10k + surge)/50 > (199*10k + surge)/200
        # That is always true for surge > 10k, since 50-day mean reacts faster.
        # Actually: SMA(50) at bar 200 = mean of bars[151..200]
        #   = (49*10_000 + surge) / 50
        # SMA(200) at bar 200 = mean of bars[1..200]
        #   = (199*10_000 + surge) / 200
        # Cross condition: (49*10k + surge)/50 > (199*10k + surge)/200
        #   => 200*(49*10k+surge) > 50*(199*10k+surge)
        #   => 200*49*10k + 200*surge > 50*199*10k + 50*surge
        #   => 9_800_000 + 200*surge > 9_950_000 + 50*surge
        #   => 150*surge > 150_000
        #   => surge > 1_000 cents = $10
        # So any surge > 10_000 + 1_000 = 11_000 cents works.
        bars.append(_make_bar("NVDA", 50_000, 200))
        return bars

    def _make_death_cross_bars(self) -> list[Bar]:
        """
        Death cross: SMA(50) crosses below SMA(200) on the last bar.

        Phase 1 (bars 0..199): rising to make SMA(50) > SMA(200).
        Then a sharp drop on the last bar brings SMA(50) below SMA(200).
        """
        bars = []
        # 200 bars of gradual rise so both SMAs are around 20_000
        for i in range(200):
            bars.append(_make_bar("NVDA", 15_000 + i * 100, i))  # 15k..34.9k
        # One big crash: SMA(50) at bar 200 = mean of bars[151..200]
        # bars[151..199] are at 15k+151*100..15k+199*100 = 30.1k..34.9k → mean ≈ 32.5k
        # bar 200 = 1_000 (crash)
        # SMA(50) ≈ (49 * avg(30.1k..34.9k) + 1000) / 50 ≈ (49*32500 + 1000) / 50 ≈ 31930
        # SMA(200) at bar 200 = mean of bars[1..200]
        # = mean of (15100, 15200, ..., 34900, 1000) = roughly (sum_1_199 + 1000) / 200
        # sum_1_199 = sum of 15k+100*i for i=1..199 = 199*15k + 100*(1+2+...+199) = 2985000 + 100*19900 = 4975000
        # mean_200 = (4975000 + 1000) / 200 = 24880
        # At bar 199: SMA(50) = mean(bars[150..199]) ≈ mean(30k..34.9k) ≈ 32.45k
        #             SMA(200) = mean(bars[0..199]) ≈ 24875
        #             SMA(50) > SMA(200) → no cross yet (needed for death cross trigger)
        # At bar 200: SMA(50) ≈ 31930 vs SMA(200) ≈ 24880: still no cross!
        # We need a much bigger crash.  Let's use 10 flat high bars then a massive drop.
        bars2 = []
        for i in range(200):
            bars2.append(_make_bar("NVDA", 30_000, i))  # 200 flat bars at 30k
        # Last bar crashes to 1: SMA(50) = (49*30k + 1) / 50 ≈ 29400
        #                         SMA(200) = (199*30k + 1) / 200 ≈ 29850
        # 29400 < 29850 → death cross fires!
        # prev bar (bar 199): SMA(50) = SMA(200) = 30_000; prev fast >= prev slow ✓
        bars2.append(_make_bar("NVDA", 1, 200))
        return bars2

    def test_golden_cross_generates_buy(self):
        """SMA(50) crosses above SMA(200) on last bar → BUY signal."""
        bars = self._make_golden_cross_bars()
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"NVDA": bars},
            latest_prices={"NVDA": bars[-1].close_cents},
        )
        account = _make_account(cash_cents=10_000_000)
        strategy = PositionGoldenCrossStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        buy_signals = [s for s in signals if s.side == "buy" and s.symbol == "NVDA"]
        assert len(buy_signals) == 1, f"Expected BUY on golden cross, got {signals}"
        assert buy_signals[0].quantity > 0

    def test_death_cross_generates_sell_when_position_held(self):
        """SMA(50) crosses below SMA(200) on last bar + position held → SELL signal."""
        bars = self._make_death_cross_bars()
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"NVDA": bars},
            latest_prices={"NVDA": bars[-1].close_cents},
        )
        account = _make_account(
            cash_cents=5_000_000,
            positions=[PositionView("NVDA", 10, 30_000)],
        )
        strategy = PositionGoldenCrossStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        sell_signals = [s for s in signals if s.side == "sell" and s.symbol == "NVDA"]
        assert len(sell_signals) == 1, f"Expected SELL on death cross, got {signals}"
        assert sell_signals[0].quantity == 10

    def test_requires_enough_history(self):
        """Fewer than sma_slow + 1 bars → no signals."""
        bars = [_make_bar("NVDA", 30_000, i) for i in range(50)]  # too few
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"NVDA": bars},
            latest_prices={"NVDA": bars[-1].close_cents},
        )
        account = _make_account()
        strategy = PositionGoldenCrossStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        assert signals == []

    def test_no_buy_when_position_already_open(self):
        """Golden cross fires but we already hold → no additional BUY."""
        bars = self._make_golden_cross_bars()
        ctx = MarketContext(
            as_of=bars[-1].ts,
            bars={"NVDA": bars},
            latest_prices={"NVDA": bars[-1].close_cents},
        )
        account = _make_account(
            cash_cents=10_000_000,
            positions=[PositionView("NVDA", 10, 10_000)],
        )
        strategy = PositionGoldenCrossStrategy()
        signals = strategy.generate_signals(ctx, account, self.PARAMS)
        buy_signals = [s for s in signals if s.side == "buy"]
        assert buy_signals == []

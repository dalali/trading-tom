"""
Backtest runner tests.

Coverage:
  - Fill model: fills at bar[t+1].open_cents, not bar[t].close_cents
  - Look-ahead guard: strategy never sees bars beyond as_of
  - final_evaluation(confirm=False) raises ValueError
  - run_optimizer is hard-wired to DataMode.DEVELOPMENT (cannot touch test split)
  - Minimum viable run produces a BacktestRun with correct shape
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from trading_tom.engine.backtest import run_backtest, final_evaluation, run_optimizer
from trading_tom.engine.base import AccountView, MarketContext, Signal
from trading_tom.data.repository import Bar, BarRepository, DataMode, SplitAccessError
from trading_tom.models.market import PriceBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(offset_days: int) -> datetime:
    return datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset_days)


def _make_price_bar(session, symbol: str, offset_days: int,
                    open_cents: int, close_cents: int,
                    split_label: str = "train") -> PriceBar:
    bar = PriceBar(
        symbol=symbol,
        interval="1d",
        ts=_ts(offset_days),
        open_cents=open_cents,
        high_cents=close_cents + 100,
        low_cents=open_cents - 100,
        close_cents=close_cents,
        volume=1_000_000,
        split_label=split_label,
    )
    session.add(bar)
    return bar


class _NeverSignalStrategy:
    """A strategy that always returns [] — useful for infrastructure testing."""
    name = "never_signal"

    def required_history(self) -> int:
        return 1

    def generate_signals(self, ctx, account, params) -> list[Signal]:
        return []


class _BuyFirstBarStrategy:
    """
    Buys 1 share of the first symbol on the very first bar.
    Lets us verify the fill price is next-bar open.
    """
    name = "buy_first"
    _bought = False

    def __init__(self):
        self._bought = False

    def required_history(self) -> int:
        return 1

    def generate_signals(self, ctx, account, params) -> list[Signal]:
        if self._bought:
            return []
        symbols = list(ctx.bars.keys())
        if not symbols:
            return []
        self._bought = True
        return [Signal(symbol=symbols[0], side="buy", quantity=1, reason="buy_first:test")]


class _LookAheadSnoopStrategy:
    """
    Records (as_of, bar_ts) pairs seen by the strategy.
    We then assert that no bar with ts > as_of was passed.
    """
    name = "snoop"

    def __init__(self):
        # list of (as_of, bar_ts) tuples - both as date objects for tz-safe comparison
        self.observations: list[tuple] = []

    def required_history(self) -> int:
        return 1

    def generate_signals(self, ctx, account, params) -> list[Signal]:
        # Normalise as_of to a date for comparison
        as_of_date = ctx.as_of.date() if hasattr(ctx.as_of, 'date') else ctx.as_of
        for symbol, bars in ctx.bars.items():
            for b in bars:
                bar_date = b.ts.date() if hasattr(b.ts, 'date') else b.ts
                self.observations.append((as_of_date, bar_date))
        return []


# ---------------------------------------------------------------------------
# Fill model: fills at bar[t+1].open_cents
# ---------------------------------------------------------------------------

class TestFillModel:
    def test_fill_uses_next_bar_open_not_current_close(self, db_session):
        """
        Bar t has close=100; bar t+1 has open=200.
        A strategy that signals BUY on bar t should fill at 200 (t+1 open),
        not at 100 (t close).
        """
        # Insert 3 bars: bar 0 (open=50, close=100), bar 1 (open=200, close=210), bar 2 stub
        _make_price_bar(db_session, "AAPL", 0, open_cents=50,  close_cents=100)
        _make_price_bar(db_session, "AAPL", 1, open_cents=200, close_cents=210)
        _make_price_bar(db_session, "AAPL", 2, open_cents=215, close_cents=220)
        db_session.commit()

        strategy = _BuyFirstBarStrategy()
        run = run_backtest(
            session=db_session,
            strategy=strategy,
            params={},
            symbols=["AAPL"],
            data_split="train",
            mode=DataMode.DEVELOPMENT,
            starting_capital_cents=1_000_000,
        )

        from trading_tom.models.trade import Trade
        trades = db_session.query(Trade).filter(Trade.side == "buy").all()
        assert len(trades) == 1, f"Expected 1 buy trade, got {len(trades)}"
        # Fill price must be bar[1].open_cents = 200, not bar[0].close_cents = 100
        assert trades[0].price_cents == 200, (
            f"Expected fill at next-bar open (200), got {trades[0].price_cents}"
        )
        assert trades[0].price_cents != 100, "Fill must NOT use current-bar close"


# ---------------------------------------------------------------------------
# Look-ahead guard
# ---------------------------------------------------------------------------

class TestLookAheadGuard:
    def test_strategy_never_sees_future_bars(self, db_session):
        """
        At each step, the strategy context must only contain bars with ts <= as_of.
        Injecting a 'future' bar at day 99 and verifying it never appears
        in the strategy's context when the current bar is earlier.
        """
        # 5 normal bars (day 0..4) + 1 future bar far ahead (day 99)
        for i in range(5):
            _make_price_bar(db_session, "AAPL", i, open_cents=100 + i, close_cents=110 + i)
        _make_price_bar(db_session, "AAPL", 99, open_cents=9999, close_cents=9999)
        db_session.commit()

        snoop = _LookAheadSnoopStrategy()
        run_backtest(
            session=db_session,
            strategy=snoop,
            params={},
            symbols=["AAPL"],
            data_split="train",
            mode=DataMode.DEVELOPMENT,
            starting_capital_cents=1_000_000,
        )

        # run_backtest loops over all_ts[:-1], i.e. days [0,1,2,3,4].
        # The future bar is at day 99; the last bar in the loop is day 4.
        # Strategy at as_of=day4 should see bars up to day 4 only (not day 99).
        #
        # Check: for every (as_of, bar_ts) observation, bar_ts <= as_of.
        violations = [
            (as_of, bar_ts)
            for as_of, bar_ts in snoop.observations
            if bar_ts > as_of
        ]
        assert violations == [], (
            f"Look-ahead violation: strategy saw future bars: {violations}"
        )


# ---------------------------------------------------------------------------
# final_evaluation requires confirm=True
# ---------------------------------------------------------------------------

class TestFinalEvaluation:
    def test_final_evaluation_without_confirm_raises(self, db_session):
        """final_evaluation(confirm=False) must raise ValueError — prevents accidents."""
        strategy = _NeverSignalStrategy()
        with pytest.raises(ValueError, match="confirm=True"):
            final_evaluation(
                session=db_session,
                strategy=strategy,
                params={},
                symbols=["AAPL"],
                confirm=False,
            )

    def test_final_evaluation_with_confirm_true_requires_test_bars(self, db_session):
        """
        final_evaluation(confirm=True) raises ValueError when no test bars exist,
        not a silent empty result.
        """
        # No bars in DB → should raise ValueError("No bars found")
        strategy = _NeverSignalStrategy()
        with pytest.raises(ValueError):
            final_evaluation(
                session=db_session,
                strategy=strategy,
                params={},
                symbols=["AAPL"],
                confirm=True,
            )


# ---------------------------------------------------------------------------
# Optimizer hard-wired to DEVELOPMENT mode
# ---------------------------------------------------------------------------

class TestOptimizerModeHardwiring:
    def test_optimizer_never_passes_test_split_to_repository(self, db_session):
        """
        run_optimizer must use DataMode.DEVELOPMENT internally.
        It must never construct a BarRepository with DataMode.FINAL_EVALUATION,
        which would allow reading the test split.

        We verify this by monkeypatching BarRepository.__init__ to record the
        mode it was called with, then assert FINAL_EVALUATION never appeared.
        """
        recorded_modes = []
        original_init = BarRepository.__init__

        def recording_init(self, session, mode):
            recorded_modes.append(mode)
            original_init(self, session, mode)

        # Insert minimal bars for the optimizer to try (train + validation)
        for i in range(3):
            _make_price_bar(db_session, "SPY", i,
                            open_cents=100 + i, close_cents=110 + i,
                            split_label="train")
            _make_price_bar(db_session, "SPY", i + 10,
                            open_cents=200 + i, close_cents=210 + i,
                            split_label="validation")
        db_session.commit()

        strategy = _NeverSignalStrategy()
        param_grid = {"dummy": [1]}  # one combination

        with patch.object(BarRepository, "__init__", recording_init):
            try:
                run_optimizer(
                    session=db_session,
                    strategy=strategy,
                    param_grid=param_grid,
                    symbols=["SPY"],
                )
            except Exception:
                pass  # may fail due to not enough bars; that's ok

        assert DataMode.FINAL_EVALUATION not in recorded_modes, (
            f"Optimizer used FINAL_EVALUATION mode: {recorded_modes}"
        )
        # Must have used DEVELOPMENT mode
        assert DataMode.DEVELOPMENT in recorded_modes, (
            f"Optimizer did not use DEVELOPMENT mode: {recorded_modes}"
        )

    def test_optimizer_development_mode_blocks_test_split(self, db_session):
        """
        If the optimizer tried to pass a 'test' split with DEVELOPMENT mode,
        BarRepository would raise SplitAccessError.
        This confirms the enforcement is active.
        """
        _make_price_bar(db_session, "AAPL", 0, open_cents=100, close_cents=110,
                        split_label="test")
        db_session.commit()

        repo = BarRepository(db_session, DataMode.DEVELOPMENT)
        with pytest.raises(SplitAccessError):
            repo.get_bars("AAPL", "1d", splits={"test"})


# ---------------------------------------------------------------------------
# Minimum viable backtest run
# ---------------------------------------------------------------------------

class TestBacktestRun:
    def test_run_returns_backtest_run_with_metrics(self, db_session):
        """A minimal run with 3 bars produces a BacktestRun with populated metrics."""
        for i in range(3):
            _make_price_bar(db_session, "AAPL", i,
                            open_cents=100 + i * 10,
                            close_cents=105 + i * 10)
        db_session.commit()

        strategy = _NeverSignalStrategy()
        run = run_backtest(
            session=db_session,
            strategy=strategy,
            params={},
            symbols=["AAPL"],
            data_split="train",
            mode=DataMode.DEVELOPMENT,
            starting_capital_cents=1_000_000,
        )

        assert run is not None
        assert run.strategy_name == "never_signal"
        assert "total_return" in run.metrics
        assert "sharpe" in run.metrics
        assert "max_drawdown" in run.metrics
        assert "win_rate" in run.metrics

    def test_run_raises_when_no_bars_found(self, db_session):
        """No bars for the requested symbol/split → ValueError."""
        strategy = _NeverSignalStrategy()
        with pytest.raises(ValueError, match="No bars found"):
            run_backtest(
                session=db_session,
                strategy=strategy,
                params={},
                symbols=["AAPL"],
                data_split="train",
                mode=DataMode.DEVELOPMENT,
            )

    def test_run_raises_when_only_one_bar(self, db_session):
        """Single bar → not enough to do bar[t+1] fill → ValueError."""
        _make_price_bar(db_session, "AAPL", 0, open_cents=100, close_cents=110)
        db_session.commit()

        strategy = _NeverSignalStrategy()
        with pytest.raises(ValueError, match="Not enough bars"):
            run_backtest(
                session=db_session,
                strategy=strategy,
                params={},
                symbols=["AAPL"],
                data_split="train",
                mode=DataMode.DEVELOPMENT,
            )

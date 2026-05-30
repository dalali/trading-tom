"""
Unit tests for compute_metrics.

Tests known equity series and trade P&L lists against analytically
computed expected values.
"""
import math
import pytest

from trading_tom.engine.metrics import compute_metrics, Metrics


class TestTotalReturn:
    def test_known_equity_series(self):
        """[100, 110, 105, 115] → total_return = (115 - 100) / 100 = 0.15."""
        m = compute_metrics(
            equity_series=[100, 110, 105, 115],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        assert m.total_return == pytest.approx(0.15, abs=1e-9)

    def test_loss_run_negative_return(self):
        """Equity falls from 1000 to 800 → total_return = -0.20."""
        m = compute_metrics(
            equity_series=[1000, 900, 850, 800],
            closing_trades_pnl=[-200],
            total_fees_cents=0,
            starting_capital_cents=1000,
        )
        assert m.total_return == pytest.approx(-0.20, abs=1e-9)

    def test_empty_equity_series_uses_starting_capital(self):
        """Empty series → total_return = 0 (final == starting)."""
        m = compute_metrics(
            equity_series=[],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        assert m.total_return == 0.0

    def test_zero_starting_capital_does_not_divide_by_zero(self):
        """If starting_capital = 0, return is 0 not a ZeroDivisionError."""
        m = compute_metrics(
            equity_series=[0, 100],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=0,
        )
        assert m.total_return == 0.0


class TestMaxDrawdown:
    def test_known_drawdown(self):
        """
        Equity [100, 110, 105, 115]:
          Peak after bar 0 = 100; after bar 1 = 110; after bar 2 = 110 (no new peak).
          Drawdown at bar 2 = (105 - 110) / 110 = -5/110 ≈ -0.04545.
          Bar 3: 115 > 110, new peak; dd = 0.
          Max drawdown = -5/110.
        """
        m = compute_metrics(
            equity_series=[100, 110, 105, 115],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        expected_dd = (105 - 110) / 110
        assert m.max_drawdown == pytest.approx(expected_dd, abs=1e-9)

    def test_monotone_rising_series_zero_drawdown(self):
        """Always rising equity → max_drawdown = 0."""
        m = compute_metrics(
            equity_series=[100, 110, 120, 130],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        assert m.max_drawdown == 0.0

    def test_all_falling_series_large_drawdown(self):
        """100 → 50 → 25: max drawdown = (25 - 100) / 100 = -0.75."""
        m = compute_metrics(
            equity_series=[100, 50, 25],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        assert m.max_drawdown == pytest.approx(-0.75, abs=1e-9)

    def test_single_bar_zero_drawdown(self):
        """Single-element series → drawdown = 0 (no previous peak)."""
        m = compute_metrics(
            equity_series=[1_000_000],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        assert m.max_drawdown == 0.0


class TestWinRate:
    def test_all_wins(self):
        """Three profitable trades → win_rate = 1.0."""
        m = compute_metrics(
            equity_series=[100, 110, 120, 130],
            closing_trades_pnl=[100, 200, 300],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        assert m.win_rate == 1.0

    def test_all_losses(self):
        """Three losing trades → win_rate = 0.0."""
        m = compute_metrics(
            equity_series=[1000, 900, 800, 700],
            closing_trades_pnl=[-100, -200, -300],
            total_fees_cents=0,
            starting_capital_cents=1000,
        )
        assert m.win_rate == 0.0

    def test_mixed_win_rate(self):
        """2 wins and 1 loss → win_rate = 2/3."""
        m = compute_metrics(
            equity_series=[100, 110, 120, 115],
            closing_trades_pnl=[200, 300, -50],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        assert m.win_rate == pytest.approx(2 / 3, abs=1e-9)

    def test_empty_trades_win_rate_zero(self):
        """No closing trades → win_rate = 0, no ZeroDivisionError."""
        m = compute_metrics(
            equity_series=[1_000_000, 1_000_000],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        assert m.win_rate == 0.0

    def test_breakeven_trade_not_a_win(self):
        """A trade with pnl=0 is not counted as a win."""
        m = compute_metrics(
            equity_series=[100, 100, 110],
            closing_trades_pnl=[0, 100],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        # 1 win (100), 1 not-win (0) → win_rate = 0.5
        assert m.win_rate == pytest.approx(0.5, abs=1e-9)


class TestSharpe:
    def test_single_trade_no_crash(self):
        """Single bar → only one return → std=0 → sharpe=0, no crash."""
        m = compute_metrics(
            equity_series=[1_000_000, 1_010_000],
            closing_trades_pnl=[10_000],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        # std=0 → sharpe=0 by convention
        assert m.sharpe == 0.0

    def test_empty_trades_no_crash(self):
        """Empty trades list → sharpe = 0, no crash."""
        m = compute_metrics(
            equity_series=[],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        assert m.sharpe == 0.0

    def test_steady_gain_series_produces_finite_sharpe(self):
        """
        Equity [100, 101, 102, 103]: near-constant 1% daily gains.
        Returns are not exactly equal due to arithmetic progression,
        so variance is near-zero but non-zero → very high Sharpe.
        Just verify it's finite and positive (strong risk-adjusted performance).
        """
        m = compute_metrics(
            equity_series=[100, 101, 102, 103],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        assert math.isfinite(m.sharpe)
        assert m.sharpe > 0  # positive return → positive sharpe

    def test_varying_returns_produce_nonzero_sharpe(self):
        """Returns that have variability should produce a non-zero Sharpe."""
        # Mix of gains and losses
        equity = [1_000_000, 1_010_000, 990_000, 1_020_000, 1_005_000]
        m = compute_metrics(
            equity_series=equity,
            closing_trades_pnl=[10_000, -10_000, 20_000, -5_000],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        # Just verify it doesn't crash and produces a finite float
        assert math.isfinite(m.sharpe)


class TestTradeCountAndFees:
    def test_n_trades_matches_closing_pnl_list_length(self):
        m = compute_metrics(
            equity_series=[100, 110],
            closing_trades_pnl=[50, 75, -25],
            total_fees_cents=10,
            starting_capital_cents=100,
        )
        assert m.n_trades == 3

    def test_fees_cents_matches_input(self):
        m = compute_metrics(
            equity_series=[100, 110],
            closing_trades_pnl=[100],
            total_fees_cents=42,
            starting_capital_cents=100,
        )
        assert m.fees_cents == 42

    def test_gross_pnl_is_sum_of_closing_pnl(self):
        """gross_pnl_cents = sum(closing_trades_pnl)."""
        pnl = [100, -50, 200, -30]
        m = compute_metrics(
            equity_series=[100, 110],
            closing_trades_pnl=pnl,
            total_fees_cents=0,
            starting_capital_cents=100,
        )
        assert m.gross_pnl_cents == sum(pnl)

    def test_all_zeros_metrics_no_crash(self):
        """Empty/zero inputs → all metrics are zero, no exceptions."""
        m = compute_metrics(
            equity_series=[],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        assert m.total_return == 0.0
        assert m.win_rate == 0.0
        assert m.max_drawdown == 0.0
        assert m.sharpe == 0.0
        assert m.n_trades == 0
        assert m.gross_pnl_cents == 0
        assert m.fees_cents == 0

    def test_returns_named_tuple(self):
        """compute_metrics returns a Metrics NamedTuple."""
        m = compute_metrics(
            equity_series=[1_000_000],
            closing_trades_pnl=[],
            total_fees_cents=0,
            starting_capital_cents=1_000_000,
        )
        assert isinstance(m, Metrics)

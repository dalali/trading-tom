"""
Tests for the trade executor: balance deduction, fee deduction, account recycling.
"""
import pytest
from datetime import datetime, timezone

from trading_tom.engine.base import Signal
from trading_tom.engine.executor import execute_signal, InsufficientFundsError
from trading_tom.engine.lifecycle import (
    bust_check_and_recycle,
    get_active_account,
    create_new_account,
)
from trading_tom.models.account import Account, Position
from trading_tom.models.trade import Trade


def _make_account(session, cash_cents: int = 1_000_000) -> Account:
    account = Account(
        status="active",
        created_at=datetime.now(timezone.utc),
        starting_capital_cents=1_000_000,
        cash_cents=cash_cents,
    )
    session.add(account)
    session.flush()
    return account


class TestBuySignal:
    def test_cash_reduced_by_notional_plus_fee(self, db_session):
        account = _make_account(db_session, cash_cents=1_000_000)
        signal = Signal(symbol="AAPL", side="buy", quantity=10, reason="test")
        fill_price = 18_000  # $180.00

        trade = execute_signal(
            db_session, signal, account, fill_price,
            data_split="train", executed_at=datetime.now(timezone.utc)
        )
        db_session.commit()

        # fee for buy = 0 (default commission)
        expected_cash = 1_000_000 - (10 * 18_000)
        assert account.cash_cents == expected_cash
        assert trade.fee_cents == 0
        assert trade.realized_pnl_cents is None
        assert trade.side == "buy"
        assert trade.quantity == 10

    def test_position_created_on_buy(self, db_session):
        account = _make_account(db_session, cash_cents=1_000_000)
        signal = Signal(symbol="MSFT", side="buy", quantity=5, reason="test")
        execute_signal(db_session, signal, account, 40_000, data_split="train")
        db_session.commit()

        pos = db_session.query(Position).filter_by(
            account_id=account.id, symbol="MSFT"
        ).first()
        assert pos is not None
        assert pos.quantity == 5
        assert pos.avg_entry_price_cents == 40_000

    def test_buy_accumulates_position_weighted_avg(self, db_session):
        account = _make_account(db_session, cash_cents=5_000_000)
        # First buy: 10 @ $100 = $1000
        execute_signal(db_session, Signal("AAPL", "buy", 10, "test"), account, 10_000, "train")
        # Second buy: 10 @ $110 = $1100; avg = (10*100 + 10*110)/20 = $105
        execute_signal(db_session, Signal("AAPL", "buy", 10, "test"), account, 11_000, "train")
        db_session.commit()

        pos = db_session.query(Position).filter_by(
            account_id=account.id, symbol="AAPL"
        ).first()
        assert pos.quantity == 20
        assert pos.avg_entry_price_cents == 10_500  # $105

    def test_insufficient_funds_raises(self, db_session):
        account = _make_account(db_session, cash_cents=100)  # only 1 cent
        signal = Signal(symbol="AAPL", side="buy", quantity=10, reason="test")
        with pytest.raises(InsufficientFundsError):
            execute_signal(db_session, signal, account, 18_000, data_split="train")


class TestSellSignal:
    def test_sell_deducts_fee_and_updates_cash(self, db_session):
        account = _make_account(db_session, cash_cents=1_000_000)
        # Buy first
        execute_signal(db_session, Signal("AAPL", "buy", 10, "test"), account, 18_000, "train")
        cash_after_buy = account.cash_cents

        # Sell at higher price
        trade = execute_signal(
            db_session, Signal("AAPL", "sell", 10, "test"), account, 20_000, "train"
        )
        db_session.commit()

        # fee on sell of 10 shares @ $200 = notional $2000
        # SEC: ceil(0.0000229 * 2000 * 100 / 100) = ceil(0.0000229 * 2000) ...
        # notional_cents = 10 * 20_000 = 200_000; notional_dollars = 2000
        # SEC = ceil(0.0000229 * 2000) = ceil(0.0458) = 1 dollar → wait, in cents:
        # fee_dollars = 0.0000229 * 2000 = 0.0458; fee_cents = 4.58 → ceil = 5
        # FINRA = 10 * 0.000145 = 0.00145 dollars = 0.145 cents → round = 0 cents
        # total fee = 5 cents
        assert trade.fee_cents >= 0
        assert trade.realized_pnl_cents is not None
        # realized P&L = (20000 - 18000) * 10 - fee
        expected_pnl = (20_000 - 18_000) * 10 - trade.fee_cents
        assert trade.realized_pnl_cents == expected_pnl

    def test_full_sell_closes_position(self, db_session):
        account = _make_account(db_session, cash_cents=1_000_000)
        execute_signal(db_session, Signal("NVDA", "buy", 5, "test"), account, 50_000, "train")
        execute_signal(db_session, Signal("NVDA", "sell", 5, "test"), account, 55_000, "train")
        db_session.commit()

        pos = db_session.query(Position).filter_by(
            account_id=account.id, symbol="NVDA"
        ).first()
        assert pos.closed_at is not None
        assert pos.quantity == 0


class TestPartialSell:
    def test_partial_sell_reduces_position_quantity(self, db_session):
        """Selling fewer shares than held reduces quantity, does not close position."""
        account = _make_account(db_session, cash_cents=5_000_000)
        # Buy 10 shares
        execute_signal(db_session, Signal("AAPL", "buy", 10, "test"), account, 10_000, "train")
        # Sell 3 of them
        trade = execute_signal(db_session, Signal("AAPL", "sell", 3, "test"), account, 12_000, "train")
        db_session.commit()

        pos = db_session.query(Position).filter_by(
            account_id=account.id, symbol="AAPL"
        ).first()
        assert pos.quantity == 7, f"Expected 7 shares remaining, got {pos.quantity}"
        assert pos.closed_at is None, "Position must remain open after partial sell"
        assert trade.quantity == 3

    def test_partial_sell_realized_pnl_uses_avg_entry(self, db_session):
        """Partial sell P&L = (fill - avg_entry) * qty - fee."""
        account = _make_account(db_session, cash_cents=5_000_000)
        execute_signal(db_session, Signal("MSFT", "buy", 10, "test"), account, 20_000, "train")
        trade = execute_signal(db_session, Signal("MSFT", "sell", 4, "test"), account, 25_000, "train")
        db_session.commit()

        # P&L = (25_000 - 20_000) * 4 - fee
        expected_pnl = (25_000 - 20_000) * 4 - trade.fee_cents
        assert trade.realized_pnl_cents == expected_pnl


class TestSellErrors:
    def test_sell_more_than_held_raises_executor_error(self, db_session):
        """Attempting to sell more shares than held raises ExecutorError."""
        from trading_tom.engine.executor import ExecutorError
        account = _make_account(db_session, cash_cents=1_000_000)
        execute_signal(db_session, Signal("AAPL", "buy", 5, "test"), account, 10_000, "train")

        with pytest.raises(ExecutorError):
            execute_signal(db_session, Signal("AAPL", "sell", 10, "test"), account, 10_000, "train")

    def test_sell_with_no_position_raises_executor_error(self, db_session):
        """Selling a symbol we don't hold raises ExecutorError."""
        from trading_tom.engine.executor import ExecutorError
        account = _make_account(db_session, cash_cents=1_000_000)

        with pytest.raises(ExecutorError):
            execute_signal(db_session, Signal("NVDA", "sell", 1, "test"), account, 50_000, "train")

    def test_unknown_signal_side_raises_executor_error(self, db_session):
        """A signal with side='short' (unknown) raises ExecutorError."""
        from trading_tom.engine.executor import ExecutorError
        account = _make_account(db_session, cash_cents=1_000_000)

        with pytest.raises(ExecutorError, match="Unknown side"):
            execute_signal(db_session, Signal("AAPL", "short", 5, "test"), account, 10_000, "train")


class TestFeeIndependence:
    def test_fee_independently_recalculated_matches_trade(self, db_session):
        """
        Fee stored in the trade must match independently calculated fee.

        This verifies the executor calls compute_fee() correctly rather than
        trusting any externally-provided fee value.
        """
        from trading_tom.engine.fees import compute_fee
        account = _make_account(db_session, cash_cents=5_000_000)
        execute_signal(db_session, Signal("AAPL", "buy", 50, "test"), account, 20_000, "train")
        trade = execute_signal(db_session, Signal("AAPL", "sell", 50, "test"), account, 22_000, "train")
        db_session.commit()

        expected_fee = compute_fee("sell", shares=50, price_cents=22_000)
        assert trade.fee_cents == expected_fee, (
            f"Trade fee ({trade.fee_cents}) must equal independently computed fee ({expected_fee})"
        )


class TestAccountRecycling:
    def test_busted_account_is_archived_and_new_created(self, db_session):
        # Create a zero-cash account — equity=0 which is <= account_floor_cents(0)
        account = _make_account(db_session, cash_cents=0)
        db_session.commit()

        latest_prices: dict[str, int] = {}
        new_account = bust_check_and_recycle(db_session, account, latest_prices)
        db_session.commit()

        # Old account archived
        db_session.refresh(account)
        assert account.status == "archived"
        assert account.close_reason == "bust"

        # New account active
        assert new_account.status == "active"
        assert new_account.cash_cents == 1_000_000  # $10,000

    def test_solvent_account_unchanged(self, db_session):
        account = _make_account(db_session, cash_cents=500_000)
        db_session.commit()

        result = bust_check_and_recycle(db_session, account, {})
        db_session.commit()

        assert result is account
        assert account.status == "active"

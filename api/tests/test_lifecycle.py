"""
Lifecycle tests: bust detection, account recycling, equity computation.

Tests the previously uncovered scenarios:
  - Bust with open positions (lifecycle liquidates them)
  - compute_equity with and without positions
  - Two consecutive busts (chained recycling)
  - Solvent account is unchanged
"""
import pytest
from datetime import datetime, timezone

from trading_tom.engine.base import Signal
from trading_tom.engine.executor import execute_signal
from trading_tom.engine.lifecycle import (
    bust_check_and_recycle,
    close_account,
    compute_equity,
    create_new_account,
    get_active_account,
)
from trading_tom.models.account import Account, Position
from trading_tom.models.trade import Trade


def _make_account(session, cash_cents: int = 1_000_000, status: str = "active") -> Account:
    account = Account(
        status=status,
        created_at=datetime.now(timezone.utc),
        starting_capital_cents=1_000_000,
        cash_cents=cash_cents,
    )
    session.add(account)
    session.flush()
    return account


def _add_position(session, account: Account, symbol: str, qty: int, price: int) -> Position:
    pos = Position(
        account_id=account.id,
        symbol=symbol,
        quantity=qty,
        avg_entry_price_cents=price,
        opened_at=datetime.now(timezone.utc),
    )
    session.add(pos)
    session.flush()
    return pos


class TestComputeEquity:
    def test_equity_no_positions_equals_cash(self, db_session):
        """With no open positions, equity == cash_cents."""
        account = _make_account(db_session, cash_cents=500_000)
        equity = compute_equity(db_session, account, latest_prices={})
        assert equity == 500_000

    def test_equity_with_position_uses_latest_price(self, db_session):
        """equity = cash + qty * latest_price."""
        account = _make_account(db_session, cash_cents=100_000)
        _add_position(db_session, account, "AAPL", qty=10, price=20_000)
        # Latest price is 25_000 (above avg entry)
        equity = compute_equity(db_session, account, latest_prices={"AAPL": 25_000})
        expected = 100_000 + 10 * 25_000  # 100k + 250k = 350k
        assert equity == expected

    def test_equity_falls_back_to_avg_entry_when_no_latest_price(self, db_session):
        """If no latest price provided, falls back to avg_entry_price_cents."""
        account = _make_account(db_session, cash_cents=100_000)
        _add_position(db_session, account, "AAPL", qty=5, price=30_000)
        equity = compute_equity(db_session, account, latest_prices={})
        expected = 100_000 + 5 * 30_000  # 100k + 150k = 250k
        assert equity == expected

    def test_equity_multiple_positions(self, db_session):
        """equity = cash + sum(qty_i * price_i) for all open positions."""
        account = _make_account(db_session, cash_cents=50_000)
        _add_position(db_session, account, "AAPL", qty=2, price=10_000)
        _add_position(db_session, account, "MSFT", qty=3, price=20_000)
        prices = {"AAPL": 12_000, "MSFT": 18_000}
        equity = compute_equity(db_session, account, latest_prices=prices)
        expected = 50_000 + 2 * 12_000 + 3 * 18_000  # 50k + 24k + 54k = 128k
        assert equity == expected

    def test_closed_positions_excluded_from_equity(self, db_session):
        """Positions with closed_at set must not count toward equity."""
        account = _make_account(db_session, cash_cents=100_000)
        pos = _add_position(db_session, account, "AAPL", qty=10, price=20_000)
        pos.closed_at = datetime.now(timezone.utc)
        db_session.flush()
        equity = compute_equity(db_session, account, latest_prices={"AAPL": 25_000})
        assert equity == 100_000  # closed position not counted


class TestBustWithNoPositions:
    def test_zero_cash_no_positions_triggers_bust(self, db_session):
        """Account with cash=0 and no positions → equity=0 ≤ floor → busted."""
        account = _make_account(db_session, cash_cents=0)
        db_session.commit()

        new_account = bust_check_and_recycle(db_session, account, {})
        db_session.commit()

        db_session.refresh(account)
        assert account.status == "archived"
        assert account.close_reason == "bust"
        assert new_account.status == "active"
        assert new_account.id != account.id

    def test_solvent_account_is_returned_unchanged(self, db_session):
        """Account with equity > floor is returned as-is."""
        account = _make_account(db_session, cash_cents=500_000)
        db_session.commit()

        result = bust_check_and_recycle(db_session, account, {})
        db_session.commit()

        assert result is account
        assert account.status == "active"

    def test_new_account_starts_at_configured_capital(self, db_session):
        """Recycled account starts at starting_capital_cents (default $10,000)."""
        from trading_tom.config import settings
        account = _make_account(db_session, cash_cents=0)
        db_session.commit()

        new_account = bust_check_and_recycle(db_session, account, {})
        db_session.commit()

        assert new_account.cash_cents == settings.starting_capital_cents


class TestBustWithOpenPositions:
    def test_bust_with_positions_liquidates_them(self, db_session):
        """
        When an account busts and has open positions, those positions
        must be liquidated (closed) and liquidation trades inserted.
        """
        # Account with 1 cent cash + open position worth something
        # Total equity = 1 + 5 * 30_000 = 150_001 (> 0) → NOT busted yet
        # To bust, we need equity = 0: cash=0, latest_prices={}
        # (no latest price → falls back to avg_entry → equity = 5 * 30_000 > 0)
        # So we need actual cash=0 AND no latest_prices so position value falls back to avg
        # But 5 * 30_000 = 150k > 0 → not busted.
        # We need equity <= 0. Only way without prices is cash=0 and no positions,
        # OR provide a latest_price of 0.
        # Let's test with latest_price = 0 (mark position to market at $0).
        account = _make_account(db_session, cash_cents=0)
        pos = _add_position(db_session, account, "AAPL", qty=5, price=30_000)
        db_session.commit()

        # With latest_price=0, equity = 0 + 5*0 = 0 → busted
        new_account = bust_check_and_recycle(
            db_session, account, latest_prices={"AAPL": 0}
        )
        db_session.commit()

        # Old account archived
        db_session.refresh(account)
        assert account.status == "archived"

        # Position must be closed
        db_session.refresh(pos)
        assert pos.closed_at is not None
        assert pos.quantity == 0

        # Liquidation trade must exist
        trades = (
            db_session.query(Trade)
            .filter(
                Trade.account_id == account.id,
                Trade.strategy_name == "lifecycle:liquidation",
            )
            .all()
        )
        assert len(trades) == 1
        assert trades[0].symbol == "AAPL"
        assert trades[0].side == "sell"
        assert trades[0].quantity == 5

    def test_bust_position_liquidated_at_avg_entry_price(self, db_session):
        """
        Bust liquidation uses avg_entry_price as fill price
        (no external price feed at liquidation time).
        P&L of liquidation at avg_entry = 0.
        """
        account = _make_account(db_session, cash_cents=0)
        _add_position(db_session, account, "TSLA", qty=3, price=50_000)
        db_session.commit()

        # Latest prices empty → equity falls back to avg_entry = 3 * 50_000 = 150k > 0
        # Not busted. Provide latest_price=0 to force bust.
        bust_check_and_recycle(db_session, account, latest_prices={"TSLA": 0})
        db_session.commit()

        trade = (
            db_session.query(Trade)
            .filter(Trade.strategy_name == "lifecycle:liquidation")
            .first()
        )
        assert trade is not None
        # Liquidation at avg_entry → realized P&L = (price - avg_entry) * qty = 0
        assert trade.realized_pnl_cents == 0
        assert trade.fee_cents == 0  # bust liquidations are fee-free


class TestChainedRecycling:
    def test_two_consecutive_busts_creates_two_new_accounts(self, db_session):
        """
        Sequence: account 1 busts → account 2 created.
        Account 2 immediately busts → account 3 created.
        Both account 1 and 2 are archived; account 3 is active.
        """
        account1 = _make_account(db_session, cash_cents=0)
        db_session.commit()

        account2 = bust_check_and_recycle(db_session, account1, {})
        db_session.commit()

        # Force account2 to bust too
        account2.cash_cents = 0
        db_session.flush()

        account3 = bust_check_and_recycle(db_session, account2, {})
        db_session.commit()

        db_session.refresh(account1)
        db_session.refresh(account2)

        assert account1.status == "archived"
        assert account2.status == "archived"
        assert account3.status == "active"
        # Three distinct accounts
        assert len({account1.id, account2.id, account3.id}) == 3


class TestCloseAccount:
    def test_close_account_sets_archived_status(self, db_session):
        """close_account sets status=archived and close_reason."""
        account = _make_account(db_session, cash_cents=100_000)
        db_session.commit()

        close_account(db_session, account, close_reason="manual")
        db_session.commit()

        db_session.refresh(account)
        assert account.status == "archived"
        assert account.close_reason == "manual"

    def test_close_account_with_position_creates_liquidation_trade(self, db_session):
        """close_account liquidates any open position."""
        account = _make_account(db_session, cash_cents=500_000)
        _add_position(db_session, account, "NVDA", qty=10, price=40_000)
        db_session.commit()

        close_account(db_session, account, close_reason="bust")
        db_session.commit()

        # Cash should increase by position value (qty * avg_entry)
        db_session.refresh(account)
        # start: 500_000 + 10 * 40_000 = 900_000 (liquidation at avg_entry)
        assert account.cash_cents == 500_000 + 10 * 40_000

        # Position closed
        pos = (
            db_session.query(Position)
            .filter_by(account_id=account.id, symbol="NVDA")
            .first()
        )
        assert pos.closed_at is not None
        assert pos.quantity == 0


class TestGetActiveAccount:
    def test_returns_active_account(self, db_session):
        """get_active_account returns the single active account."""
        account = _make_account(db_session, cash_cents=500_000)
        db_session.commit()

        result = get_active_account(db_session)
        assert result is not None
        assert result.id == account.id

    def test_returns_none_when_no_active(self, db_session):
        """get_active_account returns None if no active account exists."""
        result = get_active_account(db_session)
        assert result is None

    def test_archived_account_not_returned(self, db_session):
        """Archived accounts are not returned by get_active_account."""
        account = _make_account(db_session, cash_cents=100_000, status="archived")
        db_session.commit()

        result = get_active_account(db_session)
        assert result is None

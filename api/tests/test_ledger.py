"""
Ledger reconciliation test (NFR-9, Success Criteria #5).

Invariant: starting_capital + Σ(realized_pnl on sells) − Σ(fee_cents) == cash + open_position_cost_basis
"""
import pytest
from datetime import datetime, timezone

from trading_tom.engine.base import Signal
from trading_tom.engine.executor import execute_signal
from trading_tom.models.account import Account, Position
from trading_tom.models.trade import Trade


def _make_account(session, cash_cents: int = 1_000_000) -> Account:
    account = Account(
        status="active",
        created_at=datetime.now(timezone.utc),
        starting_capital_cents=cash_cents,
        cash_cents=cash_cents,
    )
    session.add(account)
    session.flush()
    return account


def _reconcile(session, account: Account) -> dict:
    """Compute reconciliation values and return them for assertion."""
    trades = (
        session.query(Trade)
        .filter(Trade.account_id == account.id)
        .all()
    )
    total_fees = sum(t.fee_cents for t in trades)
    total_realized_pnl = sum(
        t.realized_pnl_cents for t in trades if t.realized_pnl_cents is not None
    )

    open_positions = (
        session.query(Position)
        .filter(
            Position.account_id == account.id,
            Position.closed_at.is_(None),
            Position.quantity > 0,
        )
        .all()
    )
    open_cost_basis = sum(
        p.quantity * p.avg_entry_price_cents for p in open_positions
    )

    # LHS: what the ledger says we have
    ledger_total = account.cash_cents + open_cost_basis
    # RHS: what arithmetic says we should have
    # starting + realized_pnl_gross - fees
    # But realized_pnl already nets out fees per trade, so:
    # starting_capital + sum_of_net_realized_pnl = cash (when no open positions)
    # More precisely: starting = cash + open_cost - realized_net_pnl
    expected_cash_if_flat = account.starting_capital_cents + total_realized_pnl
    # actual = cash + open_cost should equal starting + sum_net_pnl
    return {
        "cash_cents": account.cash_cents,
        "open_cost_basis": open_cost_basis,
        "ledger_total": ledger_total,
        "total_fees": total_fees,
        "total_realized_pnl": total_realized_pnl,
        "starting_capital": account.starting_capital_cents,
    }


class TestLedgerReconciliation:
    def test_buy_only_reconciles(self, db_session):
        account = _make_account(db_session, 1_000_000)
        execute_signal(db_session, Signal("AAPL", "buy", 10, "t"), account, 10_000, "train")
        db_session.commit()

        r = _reconcile(db_session, account)
        # cash + open_cost = starting (since no realized P&L and zero buy fee)
        assert r["cash_cents"] + r["open_cost_basis"] == r["starting_capital"]

    def test_round_trip_reconciles(self, db_session):
        """Buy then sell → cash should reflect the net P&L after fees."""
        account = _make_account(db_session, 1_000_000)
        execute_signal(db_session, Signal("AAPL", "buy", 10, "t"), account, 10_000, "train")
        execute_signal(db_session, Signal("AAPL", "sell", 10, "t"), account, 12_000, "train")
        db_session.commit()

        r = _reconcile(db_session, account)
        # No open positions; cash = starting + net realized P&L
        assert r["open_cost_basis"] == 0
        assert r["cash_cents"] == r["starting_capital"] + r["total_realized_pnl"]

    def test_multiple_trades_reconcile(self, db_session):
        account = _make_account(db_session, 5_000_000)
        # Buy AAPL
        execute_signal(db_session, Signal("AAPL", "buy", 20, "t"), account, 15_000, "train")
        # Buy MSFT
        execute_signal(db_session, Signal("MSFT", "buy", 10, "t"), account, 30_000, "train")
        # Sell half AAPL at profit
        execute_signal(db_session, Signal("AAPL", "sell", 10, "t"), account, 16_000, "train")
        db_session.commit()

        r = _reconcile(db_session, account)
        # cash + open_cost_basis = starting + net_realized_pnl
        assert r["cash_cents"] + r["open_cost_basis"] == r["starting_capital"] + r["total_realized_pnl"]

    def test_losing_trade_reconciles(self, db_session):
        account = _make_account(db_session, 1_000_000)
        execute_signal(db_session, Signal("AAPL", "buy", 10, "t"), account, 20_000, "train")
        # Sell at a loss
        execute_signal(db_session, Signal("AAPL", "sell", 10, "t"), account, 18_000, "train")
        db_session.commit()

        r = _reconcile(db_session, account)
        assert r["open_cost_basis"] == 0
        assert r["total_realized_pnl"] < 0
        assert r["cash_cents"] == r["starting_capital"] + r["total_realized_pnl"]

"""
Account lifecycle: bust check, close_account, create_new_account, get_active_account.

Account recycling (A2, FR-3):
  - After fills settle, compute equity.
  - If equity <= ACCOUNT_FLOOR_CENTS: liquidate positions, archive, create new.
  - The partial-unique-index on accounts enforces one-active constraint at DB level.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from trading_tom.config import settings
from trading_tom.engine.base import Signal
from trading_tom.models.account import Account, Position
from trading_tom.models.trade import Trade

logger = logging.getLogger(__name__)


def get_active_account(session: Session) -> Account | None:
    """Return the single active account, or None if none exists."""
    return (
        session.query(Account)
        .filter(Account.status == "active")
        .first()
    )


def close_account(
    session: Session,
    account: Account,
    close_reason: str = "bust",
    closed_at: datetime | None = None,
    data_split: str = "live",
) -> None:
    """
    Liquidate all open positions at their last known price, then archive the account.
    Must be called inside a transaction that the caller commits.
    """
    if closed_at is None:
        closed_at = datetime.now(timezone.utc)

    # Liquidate open positions
    open_positions = (
        session.query(Position)
        .filter(
            Position.account_id == account.id,
            Position.closed_at.is_(None),
            Position.quantity > 0,
        )
        .all()
    )
    for pos in open_positions:
        # Use avg entry as liquidation price (last price not stored here; use avg_entry for simplicity)
        fill_price = pos.avg_entry_price_cents
        fee_cents = 0  # liquidation trades are fee-free (bust scenario)
        realized_pnl = (fill_price - pos.avg_entry_price_cents) * pos.quantity - fee_cents

        trade = Trade(
            account_id=account.id,
            symbol=pos.symbol,
            side="sell",
            quantity=pos.quantity,
            price_cents=fill_price,
            fee_cents=fee_cents,
            realized_pnl_cents=realized_pnl,
            strategy_name="lifecycle:liquidation",
            data_split=data_split,
            executed_at=closed_at,
        )
        session.add(trade)
        account.cash_cents += pos.quantity * fill_price
        pos.quantity = 0
        pos.closed_at = closed_at

    account.status = "archived"
    account.closed_at = closed_at
    account.close_reason = close_reason
    logger.info("Account #%d archived (reason=%s)", account.id, close_reason)


def create_new_account(
    session: Session,
    starting_capital_cents: int | None = None,
    status: str = "active",
) -> Account:
    """
    Create and flush a new account. Pass status="backtest" when called from backtests
    to avoid conflicting with the unique constraint on active accounts.
    """
    if starting_capital_cents is None:
        starting_capital_cents = settings.starting_capital_cents

    account = Account(
        status=status,
        created_at=datetime.now(timezone.utc),
        starting_capital_cents=starting_capital_cents,
        cash_cents=starting_capital_cents,
    )
    session.add(account)
    session.flush()
    logger.info("New account #%d created (status=%s) with %dc", account.id, status, starting_capital_cents)
    return account


def compute_equity(
    session: Session,
    account: Account,
    latest_prices: dict[str, int],
) -> int:
    """
    Compute current equity = cash + market value of open positions.
    Falls back to avg_entry_price if no latest price is available.
    """
    equity = account.cash_cents
    open_positions = (
        session.query(Position)
        .filter(
            Position.account_id == account.id,
            Position.closed_at.is_(None),
            Position.quantity > 0,
        )
        .all()
    )
    for pos in open_positions:
        price = latest_prices.get(pos.symbol, pos.avg_entry_price_cents)
        equity += pos.quantity * price
    return equity


def bust_check_and_recycle(
    session: Session,
    account: Account,
    latest_prices: dict[str, int],
    data_split: str = "live",
    account_status: str = "active",
) -> Account:
    """
    Check if the account is busted; if so, archive it and create a new one.
    Returns the active account (may be the same or a new one).
    Must be called inside a transaction.
    """
    equity = compute_equity(session, account, latest_prices)
    if equity <= settings.account_floor_cents:
        logger.warning(
            "Account #%d busted (equity=%dc <= floor=%dc)",
            account.id,
            equity,
            settings.account_floor_cents,
        )
        close_account(session, account, close_reason="bust", data_split=data_split)
        return create_new_account(session, status=account_status)
    return account

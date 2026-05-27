"""
Transactional paper-trade executor.

Each call to execute_signal():
  1. Validates the signal against account state.
  2. Computes fee.
  3. Updates position (weighted avg on buy, realized P&L on sell).
  4. Updates cash_cents.
  5. Inserts immutable Trade row.
All inside one DB transaction — rolls back on any error (NFR-7).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from trading_tom.engine.base import Signal, AccountView
from trading_tom.engine.fees import compute_fee
from trading_tom.models.account import Account, Position
from trading_tom.models.trade import Trade

logger = logging.getLogger(__name__)


class InsufficientFundsError(Exception):
    pass


class ExecutorError(Exception):
    pass


def execute_signal(
    session: Session,
    signal: Signal,
    account: Account,
    fill_price_cents: int,
    data_split: str,
    backtest_run_id: int | None = None,
    executed_at: datetime | None = None,
) -> Trade:
    """
    Execute one trade signal transactionally.

    Returns the inserted Trade row.
    Raises InsufficientFundsError if the account cannot afford a buy.
    """
    if executed_at is None:
        executed_at = datetime.now(timezone.utc)

    fee_cents = compute_fee(signal.side, signal.quantity, fill_price_cents)
    notional_cents = signal.quantity * fill_price_cents
    realized_pnl_cents: int | None = None

    if signal.side == "buy":
        total_cost = notional_cents + fee_cents
        if account.cash_cents < total_cost:
            raise InsufficientFundsError(
                f"Cannot buy {signal.quantity} {signal.symbol} @ {fill_price_cents}c "
                f"(need {total_cost}c, have {account.cash_cents}c)"
            )
        # Update position
        pos = (
            session.query(Position)
            .filter(
                Position.account_id == account.id,
                Position.symbol == signal.symbol,
                Position.closed_at.is_(None),
            )
            .first()
        )
        if pos is None:
            pos = Position(
                account_id=account.id,
                symbol=signal.symbol,
                quantity=signal.quantity,
                avg_entry_price_cents=fill_price_cents,
                opened_at=executed_at,
            )
            session.add(pos)
        else:
            # Weighted average entry
            old_cost = pos.quantity * pos.avg_entry_price_cents
            new_cost = signal.quantity * fill_price_cents
            pos.quantity += signal.quantity
            pos.avg_entry_price_cents = (old_cost + new_cost) // pos.quantity

        account.cash_cents -= total_cost

    elif signal.side == "sell":
        pos = (
            session.query(Position)
            .filter(
                Position.account_id == account.id,
                Position.symbol == signal.symbol,
                Position.closed_at.is_(None),
            )
            .first()
        )
        if pos is None or pos.quantity < signal.quantity:
            available = pos.quantity if pos else 0
            raise ExecutorError(
                f"Cannot sell {signal.quantity} {signal.symbol}: only {available} held"
            )

        # Realized P&L = (fill - avg_entry) * qty - fee
        realized_pnl_cents = (
            (fill_price_cents - pos.avg_entry_price_cents) * signal.quantity - fee_cents
        )

        pos.quantity -= signal.quantity
        if pos.quantity == 0:
            pos.closed_at = executed_at

        # Cash received = notional - fee
        account.cash_cents += (notional_cents - fee_cents)

    else:
        raise ExecutorError(f"Unknown side: {signal.side}")

    trade = Trade(
        account_id=account.id,
        symbol=signal.symbol,
        side=signal.side,
        quantity=signal.quantity,
        price_cents=fill_price_cents,
        fee_cents=fee_cents,
        realized_pnl_cents=realized_pnl_cents,
        strategy_name=signal.reason.split(":")[0] if ":" in signal.reason else signal.reason,
        data_split=data_split,
        executed_at=executed_at,
        backtest_run_id=backtest_run_id,
    )
    session.add(trade)
    session.flush()  # get trade.id without committing; caller commits the outer transaction

    logger.info(
        "Trade: %s %s %d @ %dc fee=%dc realized_pnl=%s split=%s",
        signal.side.upper(),
        signal.symbol,
        signal.quantity,
        fill_price_cents,
        fee_cents,
        realized_pnl_cents,
        data_split,
    )
    return trade

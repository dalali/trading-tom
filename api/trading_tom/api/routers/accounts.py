"""Account endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trading_tom.api.deps import get_db
from trading_tom.api.schemas import AccountDetail, AccountSummary, PositionOut
from trading_tom.models.account import Account, Position
from trading_tom.services.aggregates import (
    compute_lifetime_metrics,
    get_account_equity,
    get_latest_price,
    get_open_positions,
    get_trade_count,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _account_summary(session: Session, account: Account) -> AccountSummary:
    return AccountSummary(
        id=account.id,
        status=account.status,
        created_at=account.created_at,
        closed_at=account.closed_at,
        close_reason=account.close_reason,
        starting_capital_cents=account.starting_capital_cents,
        cash_cents=account.cash_cents,
        trade_count=get_trade_count(session, account.id),
    )


@router.get("", response_model=list[AccountSummary])
def list_accounts(session: Session = Depends(get_db)):
    accounts = session.query(Account).order_by(Account.id.desc()).all()
    return [_account_summary(session, a) for a in accounts]


@router.get("/active", response_model=AccountSummary)
def get_active_account(session: Session = Depends(get_db)):
    account = session.query(Account).filter(Account.status == "active").first()
    if account is None:
        raise HTTPException(status_code=404, detail="No active account")
    return _account_summary(session, account)


@router.get("/{account_id}", response_model=AccountDetail)
def get_account(account_id: int, session: Session = Depends(get_db)):
    account = session.query(Account).filter(Account.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    metrics = compute_lifetime_metrics(session, account)
    summary = _account_summary(session, account)
    return AccountDetail(
        **summary.model_dump(),
        lifetime_return=metrics["lifetime_return"],
        win_rate=metrics["win_rate"],
        max_drawdown=metrics["max_drawdown"],
        sharpe=metrics["sharpe"],
        total_fees_cents=metrics["total_fees_cents"],
        gross_pnl_cents=metrics["gross_pnl_cents"],
    )


@router.get("/{account_id}/positions", response_model=list[PositionOut])
def get_positions(account_id: int, session: Session = Depends(get_db)):
    account = session.query(Account).filter(Account.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    positions = get_open_positions(session, account_id)
    result = []
    for pos in positions:
        latest = get_latest_price(session, pos.symbol)
        market_value = pos.quantity * latest if latest else None
        unrealized = (
            (latest - pos.avg_entry_price_cents) * pos.quantity if latest else None
        )
        result.append(PositionOut(
            id=pos.id,
            symbol=pos.symbol,
            quantity=pos.quantity,
            avg_entry_price_cents=pos.avg_entry_price_cents,
            opened_at=pos.opened_at,
            unrealized_pnl_cents=unrealized,
            market_value_cents=market_value,
            latest_price_cents=latest,
        ))
    return result

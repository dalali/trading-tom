"""Trade history endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trading_tom.api.deps import get_db
from trading_tom.api.schemas import TradeList, TradeOut
from trading_tom.models.account import Account
from trading_tom.models.trade import Trade

router = APIRouter(prefix="/accounts", tags=["trades"])


@router.get("/{account_id}/trades", response_model=TradeList)
def list_trades(
    account_id: int,
    from_dt: Optional[datetime] = Query(None, alias="from"),
    to_dt: Optional[datetime] = Query(None, alias="to"),
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    split: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    session: Session = Depends(get_db),
):
    account = session.query(Account).filter(Account.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    q = session.query(Trade).filter(Trade.account_id == account_id)
    if from_dt:
        q = q.filter(Trade.executed_at >= from_dt)
    if to_dt:
        q = q.filter(Trade.executed_at <= to_dt)
    if symbol:
        q = q.filter(Trade.symbol == symbol)
    if side:
        q = q.filter(Trade.side == side)
    if split:
        q = q.filter(Trade.data_split == split)

    total = q.count()
    trades = (
        q.order_by(Trade.executed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return TradeList(
        trades=[TradeOut.model_validate(t) for t in trades],
        total=total,
        page=page,
        page_size=page_size,
    )

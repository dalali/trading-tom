"""Daily, weekly, and equity endpoints."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trading_tom.api.deps import get_db
from trading_tom.api.schemas import (
    DailySummary,
    DailyBreakdown,
    EquityPoint,
    PositionOut,
    TradeOut,
    WeeklySummary,
)
from trading_tom.models.account import Account
from trading_tom.models.market import EquitySnapshot
from trading_tom.services.aggregates import (
    compute_daily_summary,
    compute_weekly_summary,
    get_latest_price,
)

ET = ZoneInfo("America/New_York")
router = APIRouter(prefix="/accounts", tags=["aggregates"])


def _current_et_date() -> date:
    return datetime.now(tz=ET).date()


def _current_week_start() -> date:
    today = _current_et_date()
    return today - timedelta(days=today.weekday())  # Monday


@router.get("/{account_id}/daily", response_model=DailySummary)
def daily_summary(
    account_id: int,
    date_str: Optional[str] = Query(None, alias="date"),
    session: Session = Depends(get_db),
):
    account = session.query(Account).filter(Account.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if date_str:
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format; expected YYYY-MM-DD")
    else:
        d = _current_et_date()

    summary = compute_daily_summary(session, account, d)
    trades_out = [TradeOut.model_validate(t) for t in summary["trades"]]

    open_pos_out = []
    for pos in summary["open_positions"]:
        latest = get_latest_price(session, pos.symbol)
        market_value = pos.quantity * latest if latest else None
        unrealized = (latest - pos.avg_entry_price_cents) * pos.quantity if latest else None
        open_pos_out.append(PositionOut(
            id=pos.id,
            symbol=pos.symbol,
            quantity=pos.quantity,
            avg_entry_price_cents=pos.avg_entry_price_cents,
            opened_at=pos.opened_at,
            unrealized_pnl_cents=unrealized,
            market_value_cents=market_value,
            latest_price_cents=latest,
        ))

    return DailySummary(
        account_id=account_id,
        date=d.isoformat(),
        cash_cents=summary["cash_cents"],
        equity_cents=summary["equity_cents"],
        net_pnl_cents=summary["net_pnl_cents"],
        fees_cents=summary["fees_cents"],
        trade_count=summary["trade_count"],
        trades=trades_out,
        open_positions=open_pos_out,
    )


@router.get("/{account_id}/weekly", response_model=WeeklySummary)
def weekly_summary(
    account_id: int,
    week_start_str: Optional[str] = Query(None, alias="week_start"),
    session: Session = Depends(get_db),
):
    account = session.query(Account).filter(Account.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if week_start_str:
        try:
            week_start = date.fromisoformat(week_start_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format; expected YYYY-MM-DD")
    else:
        week_start = _current_week_start()

    week_end = week_start + timedelta(days=4)
    summary = compute_weekly_summary(session, account, week_start)

    daily_bd = [
        DailyBreakdown(
            date=d["date"],
            trade_count=d["trade_count"],
            win_pct=d["win_pct"],
            net_pnl_cents=d["net_pnl_cents"],
            fees_cents=d["fees_cents"],
        )
        for d in summary["daily_breakdown"]
    ]

    return WeeklySummary(
        account_id=account_id,
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        total_trades=summary["total_trades"],
        win_rate=summary["win_rate"],
        gross_pnl_cents=summary["gross_pnl_cents"],
        net_pnl_cents=summary["net_pnl_cents"],
        fees_cents=summary["fees_cents"],
        avg_win_cents=summary["avg_win_cents"],
        avg_loss_cents=summary["avg_loss_cents"],
        daily_breakdown=daily_bd,
    )


@router.get("/{account_id}/equity", response_model=list[EquityPoint])
def equity_series(
    account_id: int,
    range: str = Query("week", regex="^(day|week|all)$"),
    session: Session = Depends(get_db),
):
    account = session.query(Account).filter(Account.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    q = session.query(EquitySnapshot).filter(EquitySnapshot.account_id == account_id)

    if range == "day":
        now = datetime.now(ET)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(EquitySnapshot.ts >= start)
    elif range == "week":
        now = datetime.now(ET)
        week_start = now - timedelta(days=now.weekday())
        start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(EquitySnapshot.ts >= start)

    snapshots = q.order_by(EquitySnapshot.ts).all()
    return [
        EquityPoint(ts=s.ts, equity_cents=s.equity_cents, cash_cents=s.cash_cents)
        for s in snapshots
    ]

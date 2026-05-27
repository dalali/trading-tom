"""
Aggregation queries for daily/weekly summaries (ET boundaries).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import func

from trading_tom.models.account import Account, Position
from trading_tom.models.market import PriceBar
from trading_tom.models.trade import Trade

ET = ZoneInfo("America/New_York")


def _et_day_bounds(d: date) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for a full ET trading day."""
    start_et = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=ET)
    end_et = datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=ET)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _et_week_bounds(week_start: date) -> tuple[datetime, datetime]:
    """Return (mon_start, fri_end) UTC datetimes for an ET trading week."""
    start_et = datetime(week_start.year, week_start.month, week_start.day, 0, 0, 0, tzinfo=ET)
    end_date = week_start + timedelta(days=4)  # Friday
    end_et = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, 999999, tzinfo=ET)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def get_trade_count(session: Session, account_id: int) -> int:
    return session.query(func.count(Trade.id)).filter(Trade.account_id == account_id).scalar() or 0


def get_daily_trades(session: Session, account_id: int, d: date) -> list[Trade]:
    start, end = _et_day_bounds(d)
    return (
        session.query(Trade)
        .filter(
            Trade.account_id == account_id,
            Trade.executed_at >= start,
            Trade.executed_at <= end,
        )
        .order_by(Trade.executed_at)
        .all()
    )


def get_open_positions(session: Session, account_id: int) -> list[Position]:
    return (
        session.query(Position)
        .filter(
            Position.account_id == account_id,
            Position.closed_at.is_(None),
            Position.quantity > 0,
        )
        .all()
    )


def get_latest_price(session: Session, symbol: str) -> int | None:
    row = (
        session.query(PriceBar.close_cents)
        .filter(PriceBar.symbol == symbol)
        .order_by(PriceBar.ts.desc())
        .first()
    )
    return row[0] if row else None


def get_account_equity(session: Session, account: Account) -> int:
    """Compute equity = cash + market value of open positions."""
    open_pos = get_open_positions(session, account.id)
    equity = account.cash_cents
    for pos in open_pos:
        latest = get_latest_price(session, pos.symbol)
        price = latest if latest is not None else pos.avg_entry_price_cents
        equity += pos.quantity * price
    return equity


def compute_daily_summary(session: Session, account: Account, d: date) -> dict:
    trades = get_daily_trades(session, account.id, d)
    fees_cents = sum(t.fee_cents for t in trades)
    net_pnl_cents = sum(
        t.realized_pnl_cents for t in trades if t.realized_pnl_cents is not None
    )
    equity = get_account_equity(session, account)
    open_pos = get_open_positions(session, account.id)
    return {
        "trades": trades,
        "fees_cents": fees_cents,
        "net_pnl_cents": net_pnl_cents,
        "equity_cents": equity,
        "cash_cents": account.cash_cents,
        "open_positions": open_pos,
        "trade_count": len(trades),
    }


def compute_weekly_summary(session: Session, account: Account, week_start: date) -> dict:
    start_utc, end_utc = _et_week_bounds(week_start)
    trades = (
        session.query(Trade)
        .filter(
            Trade.account_id == account.id,
            Trade.executed_at >= start_utc,
            Trade.executed_at <= end_utc,
        )
        .order_by(Trade.executed_at)
        .all()
    )

    closing_trades = [t for t in trades if t.realized_pnl_cents is not None]
    wins = [t for t in closing_trades if t.realized_pnl_cents > 0]
    losses = [t for t in closing_trades if t.realized_pnl_cents <= 0]

    fees_cents = sum(t.fee_cents for t in trades)
    net_pnl_cents = sum(t.realized_pnl_cents for t in closing_trades)
    win_rate = len(wins) / len(closing_trades) if closing_trades else 0.0
    avg_win_cents = int(sum(t.realized_pnl_cents for t in wins) / len(wins)) if wins else 0
    avg_loss_cents = int(sum(t.realized_pnl_cents for t in losses) / len(losses)) if losses else 0

    # Daily breakdown
    daily: dict[date, dict] = {}
    for t in trades:
        d = t.executed_at.astimezone(ET).date()
        if d not in daily:
            daily[d] = {"trades": [], "wins": 0, "fees_cents": 0, "net_pnl_cents": 0}
        daily[d]["trades"].append(t)
        daily[d]["fees_cents"] += t.fee_cents
        if t.realized_pnl_cents is not None:
            daily[d]["net_pnl_cents"] += t.realized_pnl_cents
            if t.realized_pnl_cents > 0:
                daily[d]["wins"] += 1

    daily_breakdown = []
    for d in sorted(daily.keys()):
        dd = daily[d]
        total = len(dd["trades"])
        closing = sum(1 for t in dd["trades"] if t.realized_pnl_cents is not None)
        win_pct = dd["wins"] / closing if closing > 0 else 0.0
        daily_breakdown.append({
            "date": d.isoformat(),
            "trade_count": total,
            "win_pct": win_pct,
            "net_pnl_cents": dd["net_pnl_cents"],
            "fees_cents": dd["fees_cents"],
        })

    return {
        "total_trades": len(trades),
        "win_rate": win_rate,
        "gross_pnl_cents": net_pnl_cents + fees_cents,
        "net_pnl_cents": net_pnl_cents,
        "fees_cents": fees_cents,
        "avg_win_cents": avg_win_cents,
        "avg_loss_cents": avg_loss_cents,
        "daily_breakdown": daily_breakdown,
    }


def compute_lifetime_metrics(session: Session, account: Account) -> dict:
    trades = (
        session.query(Trade)
        .filter(Trade.account_id == account.id)
        .all()
    )
    closing_trades = [t for t in trades if t.realized_pnl_cents is not None]
    wins = [t for t in closing_trades if t.realized_pnl_cents > 0]
    total_fees = sum(t.fee_cents for t in trades)
    net_pnl = sum(t.realized_pnl_cents for t in closing_trades)

    win_rate = len(wins) / len(closing_trades) if closing_trades else 0.0

    # Final cash + equity
    equity = get_account_equity(session, account)
    total_return = (equity - account.starting_capital_cents) / account.starting_capital_cents \
        if account.starting_capital_cents else 0.0

    return {
        "win_rate": win_rate,
        "total_fees_cents": total_fees,
        "gross_pnl_cents": net_pnl,
        "lifetime_return": total_return,
        "max_drawdown": 0.0,   # Would need equity snapshot series; simplified for MVP
        "sharpe": 0.0,         # Same — simplified; full calc uses equity_snapshots
    }

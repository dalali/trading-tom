"""
Tests for daily/weekly P&L aggregation.

Coverage:
  - gross_pnl = net_pnl + fees (fundamental invariant)
  - Empty trade list → all zeros
  - Daily boundary: trade on day D appears in day D summary
  - Weekly boundary: trade on Monday appears in that week's summary
  - Win/loss counts are correct
"""
import pytest
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

from trading_tom.models.account import Account
from trading_tom.models.trade import Trade
from trading_tom.services.aggregates import (
    compute_daily_summary,
    compute_weekly_summary,
)

ET = ZoneInfo("America/New_York")


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


def _make_trade(
    session,
    account_id: int,
    symbol: str = "AAPL",
    side: str = "sell",
    quantity: int = 10,
    price_cents: int = 10_000,
    fee_cents: int = 5,
    realized_pnl_cents: int | None = 100,
    executed_at: datetime | None = None,
) -> Trade:
    if executed_at is None:
        executed_at = datetime.now(timezone.utc)
    trade = Trade(
        account_id=account_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price_cents=price_cents,
        fee_cents=fee_cents,
        realized_pnl_cents=realized_pnl_cents,
        strategy_name="test",
        data_split="train",
        executed_at=executed_at,
    )
    session.add(trade)
    session.flush()
    return trade


def _et_noon(d: date) -> datetime:
    """Noon ET on the given date, converted to UTC."""
    return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=ET).astimezone(timezone.utc)


class TestComputeWeeklySummary:
    def test_gross_pnl_equals_net_plus_fees(self, db_session):
        """
        Core accounting invariant: gross_pnl = net_pnl + fees.

        gross_pnl is defined in aggregates.py as: net_pnl_cents + fees_cents.
        This test verifies that holds for a known set of trades.
        """
        account = _make_account(db_session)
        week_start = date(2024, 1, 1)  # Monday
        # Three sell trades during the week
        for i in range(3):
            _make_trade(
                db_session, account.id,
                fee_cents=10,
                realized_pnl_cents=200 - i * 100,  # 200, 100, 0
                executed_at=_et_noon(week_start),
            )
        db_session.commit()

        result = compute_weekly_summary(db_session, account, week_start)

        assert result["gross_pnl_cents"] == result["net_pnl_cents"] + result["fees_cents"], (
            "gross_pnl must equal net_pnl + fees"
        )

    def test_empty_week_all_zeros(self, db_session):
        """No trades for the week → all aggregates are zero, win_rate = 0."""
        account = _make_account(db_session)
        db_session.commit()

        result = compute_weekly_summary(db_session, account, date(2024, 1, 1))

        assert result["total_trades"] == 0
        assert result["win_rate"] == 0.0
        assert result["net_pnl_cents"] == 0
        assert result["fees_cents"] == 0
        assert result["gross_pnl_cents"] == 0

    def test_win_rate_correct(self, db_session):
        """2 profitable trades and 1 losing → win_rate = 2/3."""
        account = _make_account(db_session)
        week_start = date(2024, 1, 1)
        _make_trade(db_session, account.id, realized_pnl_cents=500, executed_at=_et_noon(week_start))
        _make_trade(db_session, account.id, realized_pnl_cents=300, executed_at=_et_noon(week_start))
        _make_trade(db_session, account.id, realized_pnl_cents=-200, executed_at=_et_noon(week_start))
        db_session.commit()

        result = compute_weekly_summary(db_session, account, week_start)
        assert result["win_rate"] == pytest.approx(2 / 3, abs=1e-9)

    def test_only_closing_trades_count_for_win_rate(self, db_session):
        """Trades with realized_pnl_cents=None (open buys) don't count toward win_rate."""
        account = _make_account(db_session)
        week_start = date(2024, 1, 1)
        # 1 closing trade (win) + 1 open buy
        _make_trade(db_session, account.id, realized_pnl_cents=100, executed_at=_et_noon(week_start))
        _make_trade(db_session, account.id, side="buy", realized_pnl_cents=None,
                    executed_at=_et_noon(week_start))
        db_session.commit()

        result = compute_weekly_summary(db_session, account, week_start)
        assert result["win_rate"] == 1.0  # 1 win out of 1 closing trade

    def test_fees_sum_across_all_trades(self, db_session):
        """fees_cents is the sum of fee_cents across all trades in the week."""
        account = _make_account(db_session)
        week_start = date(2024, 1, 1)
        _make_trade(db_session, account.id, fee_cents=10, executed_at=_et_noon(week_start))
        _make_trade(db_session, account.id, fee_cents=20, executed_at=_et_noon(week_start))
        _make_trade(db_session, account.id, fee_cents=7,  executed_at=_et_noon(week_start))
        db_session.commit()

        result = compute_weekly_summary(db_session, account, week_start)
        assert result["fees_cents"] == 37

    def test_trade_outside_week_not_included(self, db_session):
        """A trade from the prior week must not appear in this week's summary."""
        account = _make_account(db_session)
        this_week = date(2024, 1, 8)   # Monday Jan 8
        last_week = date(2024, 1, 1)   # Monday Jan 1

        _make_trade(db_session, account.id, realized_pnl_cents=500,
                    executed_at=_et_noon(last_week))  # in last week
        db_session.commit()

        result = compute_weekly_summary(db_session, account, this_week)
        assert result["total_trades"] == 0
        assert result["net_pnl_cents"] == 0


class TestComputeDailySummary:
    def test_empty_day_all_zeros(self, db_session):
        """No trades on a given day → trade_count=0, fees=0."""
        account = _make_account(db_session)
        db_session.commit()

        result = compute_daily_summary(db_session, account, date(2024, 1, 1))
        assert result["trade_count"] == 0
        assert result["fees_cents"] == 0
        assert result["net_pnl_cents"] == 0

    def test_trade_on_day_appears_in_daily_summary(self, db_session):
        """A trade executed on day D must appear in day D's summary."""
        account = _make_account(db_session)
        d = date(2024, 3, 15)
        _make_trade(db_session, account.id, fee_cents=5, realized_pnl_cents=100,
                    executed_at=_et_noon(d))
        db_session.commit()

        result = compute_daily_summary(db_session, account, d)
        assert result["trade_count"] == 1
        assert result["fees_cents"] == 5
        assert result["net_pnl_cents"] == 100

    def test_trade_on_different_day_excluded(self, db_session):
        """A trade from yesterday must not appear in today's daily summary."""
        account = _make_account(db_session)
        yesterday = date(2024, 3, 14)
        today = date(2024, 3, 15)
        _make_trade(db_session, account.id, executed_at=_et_noon(yesterday))
        db_session.commit()

        result = compute_daily_summary(db_session, account, today)
        assert result["trade_count"] == 0

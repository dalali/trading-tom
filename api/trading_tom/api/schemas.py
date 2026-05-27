"""Pydantic request/response models. All money in cents."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


# --- Accounts ---

class AccountSummary(BaseModel):
    id: int
    status: str
    created_at: datetime
    closed_at: Optional[datetime]
    close_reason: Optional[str]
    starting_capital_cents: int
    cash_cents: int
    trade_count: int = 0

    class Config:
        from_attributes = True


class AccountDetail(AccountSummary):
    lifetime_return: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    total_fees_cents: int = 0
    gross_pnl_cents: int = 0


# --- Positions ---

class PositionOut(BaseModel):
    id: int
    symbol: str
    quantity: int
    avg_entry_price_cents: int
    opened_at: datetime
    unrealized_pnl_cents: Optional[int]
    market_value_cents: Optional[int]
    latest_price_cents: Optional[int]

    class Config:
        from_attributes = True


# --- Trades ---

class TradeOut(BaseModel):
    id: int
    account_id: int
    symbol: str
    side: str
    quantity: int
    price_cents: int
    fee_cents: int
    realized_pnl_cents: Optional[int]
    strategy_name: str
    data_split: str
    executed_at: datetime
    backtest_run_id: Optional[int]

    class Config:
        from_attributes = True


class TradeList(BaseModel):
    trades: list[TradeOut]
    total: int
    page: int
    page_size: int


# --- Daily summary ---

class DailySummary(BaseModel):
    account_id: int
    date: str
    cash_cents: int
    equity_cents: int
    net_pnl_cents: int
    fees_cents: int
    trade_count: int
    trades: list[TradeOut]
    open_positions: list[PositionOut]


# --- Weekly summary ---

class DailyBreakdown(BaseModel):
    date: str
    trade_count: int
    win_pct: float
    net_pnl_cents: int
    fees_cents: int


class WeeklySummary(BaseModel):
    account_id: int
    week_start: str
    week_end: str
    total_trades: int
    win_rate: float
    gross_pnl_cents: int
    net_pnl_cents: int
    fees_cents: int
    avg_win_cents: int
    avg_loss_cents: int
    daily_breakdown: list[DailyBreakdown]


# --- Equity snapshots ---

class EquityPoint(BaseModel):
    ts: datetime
    equity_cents: int
    cash_cents: int


# --- Engine status ---

class EngineStatusOut(BaseModel):
    actual_state: str
    desired_state: str
    last_tick_at: Optional[datetime]
    last_error: Optional[str]
    market_open: bool
    updated_at: datetime


# --- Strategy config ---

class StrategyConfigOut(BaseModel):
    strategy_name: str
    enabled: bool
    params: dict[str, Any]
    updated_at: datetime

    class Config:
        from_attributes = True


class StrategyConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    params: Optional[dict[str, Any]] = None


# --- Backtest ---

class BacktestRunOut(BaseModel):
    id: int
    strategy_name: str
    params: dict[str, Any]
    data_split: str
    symbols: list[str]
    period_start: datetime
    period_end: datetime
    seed: int
    metrics: dict[str, Any]
    final_evaluation: bool
    created_at: datetime

    class Config:
        from_attributes = True


class BacktestRequest(BaseModel):
    strategy: str
    params: dict[str, Any] = {}
    symbols: list[str]
    split: str = "validation"
    seed: int = 42


class FinalEvalRequest(BaseModel):
    strategy: str
    params: dict[str, Any] = {}
    symbols: list[str]
    seed: int = 42
    confirm: bool = False

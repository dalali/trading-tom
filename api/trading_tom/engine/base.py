"""Strategy protocol, Signal, MarketContext, and AccountView dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from trading_tom.data.repository import Bar


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: str           # 'buy' | 'sell'
    quantity: int       # whole shares; resolved from sizing rule before emission
    reason: str         # human-readable, logged


@dataclass
class PositionView:
    symbol: str
    quantity: int
    avg_entry_price_cents: int


@dataclass
class AccountView:
    account_id: int
    cash_cents: int
    equity_cents: int       # cash + market value of open positions
    open_positions: list[PositionView] = field(default_factory=list)

    def get_position(self, symbol: str) -> PositionView | None:
        for p in self.open_positions:
            if p.symbol == symbol:
                return p
        return None


@dataclass
class MarketContext:
    """
    The slice of market data visible to a strategy at the current timestamp.
    Strategies cannot see bars beyond `as_of` — this is the look-ahead guard.
    """
    as_of: datetime                         # current simulated/real timestamp
    bars: dict[str, list[Bar]]              # symbol → bars up to and including as_of
    latest_prices: dict[str, int]           # symbol → close_cents of latest bar

    def get_bars(self, symbol: str) -> list[Bar]:
        return self.bars.get(symbol, [])

    def latest_price(self, symbol: str) -> int | None:
        return self.latest_prices.get(symbol)


@runtime_checkable
class Strategy(Protocol):
    name: str

    def required_history(self) -> int:
        """Number of bars of lookback needed to produce a signal."""
        ...

    def generate_signals(
        self,
        ctx: MarketContext,
        account: AccountView,
        params: dict,
    ) -> list[Signal]:
        """Return zero or more trade signals for the current context."""
        ...

"""BarRepository — the ONLY path to price bars. Enforces DataMode anti-overfitting rules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from trading_tom.models.market import PriceBar

if TYPE_CHECKING:
    pass


class DataMode(Enum):
    DEVELOPMENT = "development"       # train + validation only
    FINAL_EVALUATION = "final_eval"   # test only
    LIVE = "live"                     # all splits (paper trading on present data)


class SplitAccessError(Exception):
    """Raised when code in the wrong DataMode tries to access a forbidden split."""


_MODE_ALLOWED: dict[DataMode, frozenset[str]] = {
    DataMode.DEVELOPMENT: frozenset({"train", "validation"}),
    DataMode.FINAL_EVALUATION: frozenset({"test"}),
    DataMode.LIVE: frozenset({"train", "validation", "test"}),
}


@dataclass
class Bar:
    symbol: str
    interval: str
    ts: datetime
    open_cents: int
    high_cents: int
    low_cents: int
    close_cents: int
    volume: int
    split_label: str


class BarRepository:
    """
    The single gateway for reading price_bars rows.

    Strategies receive a pre-sliced MarketContext built from this repository;
    they never touch the DB session directly.
    """

    def __init__(self, session: Session, mode: DataMode) -> None:
        self._session = session
        self._mode = mode

    @property
    def mode(self) -> DataMode:
        return self._mode

    def get_bars(
        self,
        symbol: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
        splits: set[str] | None = None,
    ) -> list[Bar]:
        """
        Fetch bars for symbol/interval in [start, end] filtered by split labels.

        Raises SplitAccessError if the requested splits are not permitted by
        the current DataMode.
        """
        allowed = _MODE_ALLOWED[self._mode]

        if splits is None:
            # Default: request only the splits allowed for this mode
            splits = set(allowed)
        else:
            forbidden = splits - allowed
            if forbidden:
                raise SplitAccessError(
                    f"DataMode.{self._mode.name} cannot read splits {forbidden}. "
                    f"Allowed: {allowed}"
                )

        q = (
            self._session.query(PriceBar)
            .filter(
                PriceBar.symbol == symbol,
                PriceBar.interval == interval,
                PriceBar.split_label.in_(splits),
            )
        )
        if start is not None:
            q = q.filter(PriceBar.ts >= start)
        if end is not None:
            q = q.filter(PriceBar.ts <= end)
        q = q.order_by(PriceBar.ts)

        return [
            Bar(
                symbol=row.symbol,
                interval=row.interval,
                ts=row.ts,
                open_cents=row.open_cents,
                high_cents=row.high_cents,
                low_cents=row.low_cents,
                close_cents=row.close_cents,
                volume=row.volume,
                split_label=row.split_label,
            )
            for row in q.all()
        ]

    def get_latest_bar(self, symbol: str, interval: str) -> Bar | None:
        """Return the most recent cached bar regardless of split (useful for live price lookups)."""
        row = (
            self._session.query(PriceBar)
            .filter(PriceBar.symbol == symbol, PriceBar.interval == interval)
            .order_by(PriceBar.ts.desc())
            .first()
        )
        if row is None:
            return None
        return Bar(
            symbol=row.symbol,
            interval=row.interval,
            ts=row.ts,
            open_cents=row.open_cents,
            high_cents=row.high_cents,
            low_cents=row.low_cents,
            close_cents=row.close_cents,
            volume=row.volume,
            split_label=row.split_label,
        )

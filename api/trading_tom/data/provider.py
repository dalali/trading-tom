"""Market data provider abstraction + yfinance implementation."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RawBar:
    symbol: str
    interval: str
    ts: datetime       # bar open time, UTC
    open_cents: int
    high_cents: int
    low_cents: int
    close_cents: int
    volume: int


def _price_to_cents(price: float) -> int:
    """Convert a float price to integer cents using Decimal to avoid float drift."""
    return int(Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


class MarketDataProvider(Protocol):
    def fetch_bars(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[RawBar]: ...


class YFinanceProvider:
    """Fetches OHLCV bars via yfinance. No API key required."""

    _INTERVAL_MAP = {
        "1d": "1d",
        "1m": "1m",
    }

    def fetch_bars(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[RawBar]:
        yf_interval = self._INTERVAL_MAP.get(interval, interval)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        logger.debug("Fetching %s %s bars %s → %s", symbol, interval, start_str, end_str)
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_str, end=end_str, interval=yf_interval, auto_adjust=True)
        except Exception as exc:
            logger.error("yfinance fetch error for %s %s: %s", symbol, interval, exc)
            return []

        if df is None or df.empty:
            return []

        bars: list[RawBar] = []
        for ts, row in df.iterrows():
            # Convert index to UTC datetime
            if hasattr(ts, "to_pydatetime"):
                ts_dt = ts.to_pydatetime()
            else:
                ts_dt = pd.Timestamp(ts).to_pydatetime()
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)
            else:
                ts_dt = ts_dt.astimezone(timezone.utc)

            try:
                bar = RawBar(
                    symbol=symbol,
                    interval=interval,
                    ts=ts_dt,
                    open_cents=_price_to_cents(float(row["Open"])),
                    high_cents=_price_to_cents(float(row["High"])),
                    low_cents=_price_to_cents(float(row["Low"])),
                    close_cents=_price_to_cents(float(row["Close"])),
                    volume=int(row["Volume"]),
                )
                bars.append(bar)
            except Exception as exc:
                logger.warning("Skipping bad bar for %s at %s: %s", symbol, ts_dt, exc)

        logger.debug("Fetched %d bars for %s %s", len(bars), symbol, interval)
        return bars

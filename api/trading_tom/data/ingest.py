"""Data ingest: backfill and incremental refresh with split-label assignment."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from trading_tom.config import settings
from trading_tom.data.provider import RawBar, YFinanceProvider
from trading_tom.models.market import PriceBar

logger = logging.getLogger(__name__)


def _compute_split_label(ts: datetime, min_ts: datetime, max_ts: datetime) -> str:
    """
    Assign a train/validation/test label based on chronological position.
    Train = oldest SPLIT_TRAIN_RATIO fraction, validation = next SPLIT_VALIDATION_RATIO,
    test = newest remainder.
    """
    total_seconds = (max_ts - min_ts).total_seconds()
    if total_seconds <= 0:
        return "train"
    elapsed = (ts - min_ts).total_seconds()
    frac = elapsed / total_seconds
    train_end = settings.split_train_ratio
    val_end = train_end + settings.split_validation_ratio
    if frac < train_end:
        return "train"
    elif frac < val_end:
        return "validation"
    else:
        return "test"


def _assign_split_labels(bars: list[RawBar]) -> list[tuple[RawBar, str]]:
    """Return bars paired with their split label."""
    if not bars:
        return []
    min_ts = min(b.ts for b in bars)
    max_ts = max(b.ts for b in bars)
    return [(bar, _compute_split_label(bar.ts, min_ts, max_ts)) for bar in bars]


def upsert_bars(session: Session, bars: list[RawBar], split_labels: list[str]) -> int:
    """
    Idempotently insert-or-update price_bars rows.
    Returns the number of rows affected.
    """
    if not bars:
        return 0

    rows = []
    for bar, label in zip(bars, split_labels):
        rows.append(
            {
                "symbol": bar.symbol,
                "interval": bar.interval,
                "ts": bar.ts,
                "open_cents": bar.open_cents,
                "high_cents": bar.high_cents,
                "low_cents": bar.low_cents,
                "close_cents": bar.close_cents,
                "volume": bar.volume,
                "split_label": label,
            }
        )

    stmt = pg_insert(PriceBar.__table__).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "interval", "ts"],
        set_={
            "open_cents": stmt.excluded.open_cents,
            "high_cents": stmt.excluded.high_cents,
            "low_cents": stmt.excluded.low_cents,
            "close_cents": stmt.excluded.close_cents,
            "volume": stmt.excluded.volume,
            "split_label": stmt.excluded.split_label,
        },
    )
    result = session.execute(stmt)
    session.commit()
    return result.rowcount


def backfill(
    session: Session,
    tickers: list[str] | None = None,
    days_back: int = 1825,  # ~5 years of daily bars
    provider: YFinanceProvider | None = None,
) -> dict[str, int]:
    """
    Backfill daily bars for the given tickers.
    Returns {symbol: rows_upserted}.
    """
    if tickers is None:
        tickers = settings.watchlist_tickers
    if provider is None:
        provider = YFinanceProvider()

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=days_back)
    summary: dict[str, int] = {}

    for symbol in tickers:
        try:
            bars = provider.fetch_bars(symbol, "1d", start, end)
            if not bars:
                logger.warning("No bars returned for %s", symbol)
                summary[symbol] = 0
                continue
            pairs = _assign_split_labels(bars)
            raw_bars = [p[0] for p in pairs]
            labels = [p[1] for p in pairs]
            n = upsert_bars(session, raw_bars, labels)
            summary[symbol] = n
            logger.info("Backfilled %s: %d rows", symbol, n)
        except Exception as exc:
            logger.error("Backfill error for %s: %s", symbol, exc)
            summary[symbol] = -1

    return summary


def refresh_latest(
    session: Session,
    tickers: list[str] | None = None,
    interval: str = "1d",
    provider: YFinanceProvider | None = None,
) -> dict[str, int]:
    """
    Incremental refresh: fetch recent bars since last cached ts for each symbol.
    Recomputes split labels over the full history for each symbol so boundaries stay consistent.
    """
    if tickers is None:
        tickers = settings.watchlist_tickers
    if provider is None:
        provider = YFinanceProvider()

    end = datetime.now(tz=timezone.utc)
    summary: dict[str, int] = {}

    for symbol in tickers:
        try:
            # Find last cached ts
            from sqlalchemy import func
            last_ts = (
                session.query(func.max(PriceBar.ts))
                .filter(PriceBar.symbol == symbol, PriceBar.interval == interval)
                .scalar()
            )
            if last_ts is None:
                # No cache; fall back to a short backfill
                start = end - timedelta(days=30 if interval == "1m" else 365)
            else:
                start = last_ts + timedelta(seconds=1)

            bars = provider.fetch_bars(symbol, interval, start, end)
            if not bars:
                summary[symbol] = 0
                continue

            # Re-fetch ALL bars to recompute split boundaries (necessary if history grows)
            all_bars = provider.fetch_bars(
                symbol, interval,
                end - timedelta(days=30 if interval == "1m" else 1825),
                end,
            )
            pairs = _assign_split_labels(all_bars)
            raw_bars = [p[0] for p in pairs]
            labels = [p[1] for p in pairs]
            n = upsert_bars(session, raw_bars, labels)
            summary[symbol] = n
        except Exception as exc:
            logger.error("Refresh error for %s %s: %s", symbol, interval, exc)
            summary[symbol] = -1

    return summary

"""PriceBar (OHLCV cache) and EquitySnapshot models."""
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    UniqueConstraint,
)
from trading_tom.db import Base


class PriceBar(Base):
    __tablename__ = "price_bars"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    interval = Column(String, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)
    open_cents = Column(BigInteger, nullable=False)
    high_cents = Column(BigInteger, nullable=False)
    low_cents = Column(BigInteger, nullable=False)
    close_cents = Column(BigInteger, nullable=False)
    volume = Column(BigInteger, nullable=False)
    split_label = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("interval IN ('1d','1m')", name="ck_bars_interval"),
        CheckConstraint(
            "split_label IN ('train','validation','test')",
            name="ck_bars_split_label",
        ),
        UniqueConstraint("symbol", "interval", "ts", name="uq_bars_symbol_interval_ts"),
        Index("ix_bars_lookup", "symbol", "interval", "ts"),
    )


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(BigInteger, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    equity_cents = Column(BigInteger, nullable=False)
    cash_cents = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("account_id", "ts", name="uq_equity_account_ts"),
        Index("ix_equity_account_time", "account_id", "ts"),
    )

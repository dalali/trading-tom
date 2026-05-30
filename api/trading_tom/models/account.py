"""Account and Position models."""
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    text,
)
from trading_tom.db import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime(timezone=True), nullable=True)
    close_reason = Column(String, nullable=True)
    starting_capital_cents = Column(BigInteger, nullable=False, default=1_000_000)
    cash_cents = Column(BigInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active','archived','backtest')", name="ck_accounts_status"),
        CheckConstraint(
            "close_reason IN ('bust','manual') OR close_reason IS NULL",
            name="ck_accounts_close_reason",
        ),
        Index("ix_accounts_status", "status"),
    )


class Position(Base):
    __tablename__ = "positions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(BigInteger, nullable=False)
    symbol = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    avg_entry_price_cents = Column(BigInteger, nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_positions_quantity"),
        Index(
            "ix_positions_account_open",
            "account_id",
            "symbol",
            postgresql_where=text("closed_at IS NULL"),
        ),
    )

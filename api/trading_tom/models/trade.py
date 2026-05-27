"""Trade model — immutable ledger of every simulated fill."""
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
)
from trading_tom.db import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(BigInteger, nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price_cents = Column(BigInteger, nullable=False)
    fee_cents = Column(BigInteger, nullable=False, default=0)
    realized_pnl_cents = Column(BigInteger, nullable=True)
    strategy_name = Column(String, nullable=False)
    data_split = Column(String, nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    backtest_run_id = Column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="ck_trades_side"),
        CheckConstraint("quantity > 0", name="ck_trades_quantity"),
        CheckConstraint(
            "data_split IN ('train','validation','test','live')",
            name="ck_trades_data_split",
        ),
        Index("ix_trades_account_time", "account_id", "executed_at"),
        Index("ix_trades_split", "data_split"),
    )

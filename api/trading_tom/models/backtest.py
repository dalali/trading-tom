"""BacktestRun model."""
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from trading_tom.db import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_name = Column(String, nullable=False)
    params = Column(JSONB, nullable=False)
    data_split = Column(String, nullable=False)
    symbols = Column(JSONB, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    seed = Column(Integer, nullable=False, default=42)
    metrics = Column(JSONB, nullable=False, default=dict)
    final_evaluation = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint(
            "data_split IN ('train','validation','test')",
            name="ck_backtest_data_split",
        ),
        CheckConstraint(
            "data_split <> 'test' OR final_evaluation = true",
            name="ck_backtest_test_requires_final_eval",
        ),
        Index("ix_backtests_created", "created_at"),
    )

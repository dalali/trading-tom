"""EngineState singleton and StrategyConfig models."""
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
)
from trading_tom.db import Base


class EngineState(Base):
    """Singleton row (id=1) the engine owns; the API reads/writes for control."""
    __tablename__ = "engine_state"

    id = Column(Integer, primary_key=True)
    desired_state = Column(String, nullable=False, default="running")
    actual_state = Column(String, nullable=False, default="stopped")
    last_tick_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_engine_state_singleton"),
        CheckConstraint(
            "desired_state IN ('running','stopped')",
            name="ck_engine_state_desired",
        ),
        CheckConstraint(
            "actual_state IN ('running','stopped','starting')",
            name="ck_engine_state_actual",
        ),
    )


class StrategyConfig(Base):
    """Persisted, operator-editable strategy parameters."""
    __tablename__ = "strategy_configs"

    strategy_name = Column(String, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    params = Column(JSON, nullable=False, default=dict)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

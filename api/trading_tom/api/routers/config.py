"""Strategy config read/write endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trading_tom.api.deps import get_db, require_operator_token
from trading_tom.api.schemas import StrategyConfigOut, StrategyConfigUpdate
from trading_tom.models.engine_state import StrategyConfig

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/strategies", response_model=list[StrategyConfigOut])
def list_strategies(session: Session = Depends(get_db)):
    configs = session.query(StrategyConfig).all()
    return [StrategyConfigOut.model_validate(c) for c in configs]


@router.put(
    "/strategies/{name}",
    response_model=StrategyConfigOut,
    dependencies=[Depends(require_operator_token)],
)
def update_strategy(
    name: str,
    update: StrategyConfigUpdate,
    session: Session = Depends(get_db),
):
    config = session.query(StrategyConfig).filter(StrategyConfig.strategy_name == name).first()
    if config is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    if update.enabled is not None:
        config.enabled = update.enabled
    if update.params is not None:
        config.params = update.params
    config.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(config)
    return StrategyConfigOut.model_validate(config)

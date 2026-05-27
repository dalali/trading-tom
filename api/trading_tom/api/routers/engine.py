"""Engine status and control endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trading_tom.api.deps import get_db, require_operator_token
from trading_tom.api.schemas import EngineStatusOut
from trading_tom.data.calendar import is_market_open
from trading_tom.models.engine_state import EngineState

router = APIRouter(prefix="/engine", tags=["engine"])


def _get_state(session: Session) -> EngineState:
    state = session.query(EngineState).filter(EngineState.id == 1).first()
    if state is None:
        raise HTTPException(status_code=503, detail="Engine state not initialized")
    return state


@router.get("/status", response_model=EngineStatusOut)
def engine_status(session: Session = Depends(get_db)):
    state = _get_state(session)
    return EngineStatusOut(
        actual_state=state.actual_state,
        desired_state=state.desired_state,
        last_tick_at=state.last_tick_at,
        last_error=state.last_error,
        market_open=is_market_open(),
        updated_at=state.updated_at,
    )


@router.post("/start", dependencies=[Depends(require_operator_token)])
def start_engine(session: Session = Depends(get_db)):
    state = _get_state(session)
    state.desired_state = "running"
    state.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"status": "ok", "desired_state": "running"}


@router.post("/stop", dependencies=[Depends(require_operator_token)])
def stop_engine(session: Session = Depends(get_db)):
    state = _get_state(session)
    state.desired_state = "stopped"
    state.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"status": "ok", "desired_state": "stopped"}


@router.post("/restart", dependencies=[Depends(require_operator_token)])
def restart_engine(session: Session = Depends(get_db)):
    state = _get_state(session)
    state.desired_state = "stopped"
    session.commit()
    state.desired_state = "running"
    state.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"status": "ok", "desired_state": "running"}

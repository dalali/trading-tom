"""Backtest run endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session

from trading_tom.api.deps import get_db, require_operator_token
from trading_tom.api.schemas import BacktestRunOut, BacktestRequest, FinalEvalRequest
from trading_tom.models.backtest import BacktestRun

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.get("", response_model=list[BacktestRunOut])
def list_backtests(
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_db),
):
    runs = (
        session.query(BacktestRun)
        .order_by(BacktestRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [BacktestRunOut.model_validate(r) for r in runs]


@router.get("/{run_id}", response_model=BacktestRunOut)
def get_backtest(run_id: int, session: Session = Depends(get_db)):
    run = session.query(BacktestRun).filter(BacktestRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return BacktestRunOut.model_validate(run)


@router.post("", response_model=BacktestRunOut, dependencies=[Depends(require_operator_token)])
def run_backtest_endpoint(
    req: BacktestRequest,
    session: Session = Depends(get_db),
):
    """Run a backtest in DEVELOPMENT mode (train or validation split only)."""
    if req.split not in {"train", "validation"}:
        raise HTTPException(
            status_code=400,
            detail="Only 'train' or 'validation' splits allowed via this endpoint",
        )

    from trading_tom.engine.backtest import run_backtest
    from trading_tom.data.repository import DataMode
    from trading_tom.engine.selector import _STRATEGY_MAP

    strategy = _STRATEGY_MAP.get(req.strategy)
    if strategy is None:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")

    try:
        run = run_backtest(
            session,
            strategy=strategy,
            params=req.params,
            symbols=req.symbols,
            data_split=req.split,
            mode=DataMode.DEVELOPMENT,
            seed=req.seed,
        )
        session.commit()
        return BacktestRunOut.model_validate(run)
    except Exception as exc:
        session.rollback()
        logger.exception("Backtest failed: %s", exc)
        raise HTTPException(status_code=500, detail="Backtest failed; see server logs")


@router.post(
    "/final-evaluation",
    response_model=BacktestRunOut,
    dependencies=[Depends(require_operator_token)],
)
def run_final_evaluation(
    req: FinalEvalRequest,
    session: Session = Depends(get_db),
):
    """Run the honest out-of-sample evaluation on the test split. Requires confirm=True."""
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to run final evaluation on test split",
        )

    from trading_tom.engine.backtest import final_evaluation
    from trading_tom.engine.selector import _STRATEGY_MAP

    strategy = _STRATEGY_MAP.get(req.strategy)
    if strategy is None:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")

    try:
        run = final_evaluation(
            session,
            strategy=strategy,
            params=req.params,
            symbols=req.symbols,
            seed=req.seed,
            confirm=True,
        )
        return BacktestRunOut.model_validate(run)
    except Exception as exc:
        session.rollback()
        logger.exception("Final evaluation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Final evaluation failed; see server logs")

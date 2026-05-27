"""FastAPI dependencies: DB session, operator token."""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from trading_tom.config import settings
from trading_tom.db import SessionLocal


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_operator_token(x_operator_token: str = Header(..., alias="X-Operator-Token")):
    if x_operator_token != settings.operator_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operator token",
        )
    return x_operator_token

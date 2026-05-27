"""
API endpoint tests using FastAPI TestClient.

Tests the daily/weekly/accounts endpoints with in-memory data.
"""
import pytest
from datetime import datetime, timezone, date
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from trading_tom.db import Base
from trading_tom.api.deps import get_db
from trading_tom.models.account import Account
from trading_tom.models.trade import Trade
from trading_tom.models.engine_state import EngineState, StrategyConfig


def _build_test_app(session):
    """Build the FastAPI app with the test DB session."""
    from main import app
    app.dependency_overrides[get_db] = lambda: session
    return app


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed engine state
    state = EngineState(
        id=1,
        desired_state="running",
        actual_state="running",
        updated_at=datetime.now(timezone.utc),
    )
    session.add(state)

    # Seed strategy configs
    for name, params in [
        ("day", {"fast_ma": 9, "slow_ma": 21}),
        ("swing", {"rsi_period": 14}),
        ("position", {"sma_fast": 50, "sma_slow": 200}),
    ]:
        cfg = StrategyConfig(strategy_name=name, enabled=True, params=params,
                             updated_at=datetime.now(timezone.utc))
        session.add(cfg)

    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    app = _build_test_app(test_db)
    with TestClient(app) as c:
        yield c, test_db


class TestHealth:
    def test_health(self, client):
        c, _ = client
        resp = c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestAccountsEndpoint:
    def test_list_accounts_empty(self, client):
        c, _ = client
        resp = c.get("/api/accounts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_active_account_not_found(self, client):
        c, _ = client
        resp = c.get("/api/accounts/active")
        assert resp.status_code == 404

    def test_list_accounts_with_data(self, client):
        c, session = client
        account = Account(
            status="active",
            created_at=datetime.now(timezone.utc),
            starting_capital_cents=1_000_000,
            cash_cents=1_000_000,
        )
        session.add(account)
        session.commit()

        resp = c.get("/api/accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "active"
        assert data[0]["cash_cents"] == 1_000_000

    def test_get_active_account(self, client):
        c, session = client
        account = Account(
            status="active",
            created_at=datetime.now(timezone.utc),
            starting_capital_cents=1_000_000,
            cash_cents=900_000,
        )
        session.add(account)
        session.commit()

        resp = c.get("/api/accounts/active")
        assert resp.status_code == 200
        assert resp.json()["cash_cents"] == 900_000


class TestDailySummaryEndpoint:
    def test_daily_empty(self, client):
        c, session = client
        account = Account(
            status="active",
            created_at=datetime.now(timezone.utc),
            starting_capital_cents=1_000_000,
            cash_cents=1_000_000,
        )
        session.add(account)
        session.commit()

        resp = c.get(f"/api/accounts/{account.id}/daily")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trade_count"] == 0
        assert data["fees_cents"] == 0

    def test_daily_with_trades(self, client):
        c, session = client
        account = Account(
            status="active",
            created_at=datetime.now(timezone.utc),
            starting_capital_cents=1_000_000,
            cash_cents=950_000,
        )
        session.add(account)
        session.flush()

        today = date.today()
        trade = Trade(
            account_id=account.id,
            symbol="AAPL",
            side="buy",
            quantity=10,
            price_cents=5_000,
            fee_cents=0,
            realized_pnl_cents=None,
            strategy_name="day",
            data_split="live",
            executed_at=datetime.now(timezone.utc),
        )
        session.add(trade)
        session.commit()

        resp = c.get(f"/api/accounts/{account.id}/daily?date={today.isoformat()}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trade_count"] == 1
        assert data["trades"][0]["symbol"] == "AAPL"


class TestWeeklySummaryEndpoint:
    def test_weekly_empty(self, client):
        c, session = client
        account = Account(
            status="active",
            created_at=datetime.now(timezone.utc),
            starting_capital_cents=1_000_000,
            cash_cents=1_000_000,
        )
        session.add(account)
        session.commit()

        resp = c.get(f"/api/accounts/{account.id}/weekly")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["win_rate"] == 0.0


class TestEngineEndpoint:
    def test_engine_status(self, client):
        c, _ = client
        with patch("trading_tom.api.routers.engine.is_market_open", return_value=False):
            resp = c.get("/api/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "actual_state" in data
        assert "market_open" in data

    def test_engine_start_requires_token(self, client):
        c, _ = client
        resp = c.post("/api/engine/start")
        assert resp.status_code == 422  # missing header

    def test_engine_start_bad_token(self, client):
        c, _ = client
        resp = c.post("/api/engine/start", headers={"X-Operator-Token": "wrong"})
        assert resp.status_code == 401

    def test_engine_stop_with_valid_token(self, client):
        c, _ = client
        from trading_tom.config import settings
        resp = c.post(
            "/api/engine/stop",
            headers={"X-Operator-Token": settings.operator_token},
        )
        assert resp.status_code == 200


class TestStrategyConfigEndpoint:
    def test_list_strategies(self, client):
        c, _ = client
        resp = c.get("/api/config/strategies")
        assert resp.status_code == 200
        data = resp.json()
        names = {d["strategy_name"] for d in data}
        assert "day" in names
        assert "swing" in names
        assert "position" in names

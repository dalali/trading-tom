"""Shared pytest fixtures — in-memory SQLite DB for tests."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from trading_tom.db import Base


@pytest.fixture(scope="function")
def db_session():
    """
    Create an in-memory SQLite DB per test with all tables.

    Note: We use SQLite here for speed; the production DB is Postgres.
    Tests that rely on Postgres-specific features (JSONB, partial indexes)
    should use a real Postgres instance; unit tests that only need the ORM
    schema are fine with SQLite.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # SQLite doesn't enforce CHECK constraints by default
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_con, con_record):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    # Skip Postgres-specific index expressions
    Base.metadata.create_all(engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)

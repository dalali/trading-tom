"""Shared pytest fixtures — in-memory SQLite DB for tests."""
import pytest
from sqlalchemy import create_engine, event, BigInteger, Integer
from sqlalchemy.orm import sessionmaker

from trading_tom.db import Base


def _sqlite_engine():
    """
    Create a SQLite engine that coerces BigInteger PKs to Integer so
    SQLite's rowid-based autoincrement works correctly.
    """
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    # Patch BigInteger to render as INTEGER in SQLite (needed for autoincrement PK)
    BigInteger.__init_subclass__  # noqa: touch
    orig = BigInteger.compile

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Map BigInteger → Integer so SQLite rowid autoincrement works
    with engine.begin() as conn:
        pass  # force connection pool init

    # Use DDL events to swap BigInteger for Integer
    from sqlalchemy import event as sa_event
    from sqlalchemy.engine import Engine

    @sa_event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_con, con_record):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    # Override BigInteger → Integer for SQLite DDL only
    # by monkeypatching the type visit on the dialect
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    SQLiteTypeCompiler.visit_BIGINT = lambda self, type_, **kw: "INTEGER"

    Base.metadata.create_all(engine, checkfirst=True)
    return engine


@pytest.fixture(scope="function")
def db_session():
    """
    Create an in-memory SQLite DB per test with all tables.

    Note: We use SQLite here for speed; the production DB is Postgres.
    Tests that rely on Postgres-specific features (partial indexes)
    should use a real Postgres instance; unit tests that only need the ORM
    schema are fine with SQLite.
    """
    engine = _sqlite_engine()
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)

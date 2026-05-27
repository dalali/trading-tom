"""Database engine, session factory, and declarative Base."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from trading_tom.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

import os
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine

# Default to sqlite for local dev, but expect postgres URL from environment in prod/tests
# Using a generic DB function setup
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_engine() -> Engine:
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is missing")
    return create_engine(DATABASE_URL)

SessionLocal = None
engine = None

def init_db(url: str = None):
    global engine, SessionLocal
    if url is None:
        url = DATABASE_URL
    if not url:
        raise ValueError("DATABASE_URL environment variable is missing and no url provided")
    engine = create_engine(url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    if SessionLocal is None:
        init_db()
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

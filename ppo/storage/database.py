"""SQLAlchemy engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from ppo.config import settings


class Base(DeclarativeBase):
    """Common base for all ORM models."""


engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context-manager-style DB session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Idempotent."""
    # Import models so SQLAlchemy registers them before create_all.
    from ppo.storage import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all tables. Destructive — used in tests and re-seeding."""
    from ppo.storage import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)

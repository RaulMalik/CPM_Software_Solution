"""Shared test fixtures."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ppo.storage.database import Base
from ppo.storage.models import Tenant
from ppo.storage.repositories import (
    AuditLogRepo,
    BESSStateRepo,
    LeaseRepo,
    ShedEventRepo,
    TenantRepo,
)


@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite session per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def tenant(db_session) -> Tenant:
    repo = TenantRepo(db_session)
    t = repo.create(
        name="Ørsted Flex",
        license_number="DK-EL-TRADER-0001",
        contact_email="flex@orsted.dk",
    )
    db_session.commit()
    return t


@pytest.fixture()
def repos(db_session):
    return {
        "tenant": TenantRepo(db_session),
        "lease": LeaseRepo(db_session),
        "shed": ShedEventRepo(db_session),
        "bess": BESSStateRepo(db_session),
        "audit": AuditLogRepo(db_session),
    }


@pytest.fixture()
def fixed_now() -> datetime:
    """A stable reference time for deterministic tests."""
    return datetime(2026, 6, 15, 4, 0, 0)

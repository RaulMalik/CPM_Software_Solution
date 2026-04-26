"""
FastAPI dependency injection wiring.

Constructs the core services on demand, sharing the same data-source
clients across a request lifecycle. Keeps the route handlers free of
construction noise.
"""

from __future__ import annotations

from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from ppo.core.bess_controller import BESSController
from ppo.core.capacity_forecaster import CapacityForecaster
from ppo.core.lease_manager import LeaseManager
from ppo.core.load_shedding import LoadSheddingEngine
from ppo.core.priority_engine import PriorityEngine
from ppo.data.ais_client import AISClient
from ppo.data.cruise_schedule import CruiseScheduleClient
from ppo.data.nordpool_client import NordpoolClient
from ppo.data.scada_client import SCADAClient
from ppo.storage.database import SessionLocal
from ppo.storage.repositories import (
    AuditLogRepo,
    BESSStateRepo,
    LeaseRepo,
    ShedEventRepo,
    TenantRepo,
)


# Data-source singletons (stateful clients kept at module level)
_ais: AISClient | None = None
_scada: SCADAClient | None = None
_nordpool: NordpoolClient | None = None
_schedule: CruiseScheduleClient | None = None


def set_data_clients(
    ais: AISClient,
    scada: SCADAClient,
    nordpool: NordpoolClient,
    schedule: CruiseScheduleClient,
) -> None:
    """Called once at app startup to wire the data clients."""
    global _ais, _scada, _nordpool, _schedule
    _ais = ais
    _scada = scada
    _nordpool = nordpool
    _schedule = schedule


def get_ais() -> AISClient:
    if _ais is None:
        raise RuntimeError("AIS client not initialised")
    return _ais


def get_scada() -> SCADAClient:
    if _scada is None:
        raise RuntimeError("SCADA client not initialised")
    return _scada


def get_nordpool() -> NordpoolClient:
    if _nordpool is None:
        raise RuntimeError("Nordpool client not initialised")
    return _nordpool


def get_schedule() -> CruiseScheduleClient:
    if _schedule is None:
        raise RuntimeError("Schedule client not initialised")
    return _schedule


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── Repositories (per-request) ─────────────────────────────────────

def get_tenant_repo(db: Session = Depends(get_db)) -> TenantRepo:
    return TenantRepo(db)


def get_lease_repo(db: Session = Depends(get_db)) -> LeaseRepo:
    return LeaseRepo(db)


def get_shed_event_repo(db: Session = Depends(get_db)) -> ShedEventRepo:
    return ShedEventRepo(db)


def get_bess_state_repo(db: Session = Depends(get_db)) -> BESSStateRepo:
    return BESSStateRepo(db)


def get_audit_repo(db: Session = Depends(get_db)) -> AuditLogRepo:
    return AuditLogRepo(db)


# ─── Core services (per-request) ────────────────────────────────────

def get_forecaster(
    scada: SCADAClient = Depends(get_scada),
    schedule: CruiseScheduleClient = Depends(get_schedule),
    ais: AISClient = Depends(get_ais),
) -> CapacityForecaster:
    return CapacityForecaster(scada=scada, schedule=schedule, ais=ais)


def get_lease_manager(
    forecaster: CapacityForecaster = Depends(get_forecaster),
    lease_repo: LeaseRepo = Depends(get_lease_repo),
    tenant_repo: TenantRepo = Depends(get_tenant_repo),
    audit_repo: AuditLogRepo = Depends(get_audit_repo),
) -> LeaseManager:
    return LeaseManager(forecaster, lease_repo, tenant_repo, audit_repo)


def get_shedding_engine(
    scada: SCADAClient = Depends(get_scada),
    ais: AISClient = Depends(get_ais),
    schedule: CruiseScheduleClient = Depends(get_schedule),
    lease_repo: LeaseRepo = Depends(get_lease_repo),
    shed_repo: ShedEventRepo = Depends(get_shed_event_repo),
    audit_repo: AuditLogRepo = Depends(get_audit_repo),
) -> LoadSheddingEngine:
    return LoadSheddingEngine(
        scada, ais, schedule, lease_repo, shed_repo, audit_repo
    )


def get_bess_controller(
    ais: AISClient = Depends(get_ais),
    nordpool: NordpoolClient = Depends(get_nordpool),
    bess_repo: BESSStateRepo = Depends(get_bess_state_repo),
    audit_repo: AuditLogRepo = Depends(get_audit_repo),
) -> BESSController:
    return BESSController(ais, nordpool, bess_repo, audit_repo)


def get_priority_engine(
    forecaster: CapacityForecaster = Depends(get_forecaster),
    lease_manager: LeaseManager = Depends(get_lease_manager),
    shedding: LoadSheddingEngine = Depends(get_shedding_engine),
    bess: BESSController = Depends(get_bess_controller),
    scada: SCADAClient = Depends(get_scada),
    audit_repo: AuditLogRepo = Depends(get_audit_repo),
) -> PriorityEngine:
    return PriorityEngine(
        forecaster, lease_manager, shedding, bess, scada, audit_repo
    )

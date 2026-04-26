"""
FastAPI application factory.

Wires the routes, templates, scheduler, and data clients. On startup,
initialises the database and registers a background job that calls
``PriorityEngine.tick()`` every ``forecast_refresh_minutes`` minutes.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from ppo.api import deps
from ppo.api.routes import (
    bess,
    capacity,
    dashboard,
    events,
    leases,
    system,
    tenants,
)
from ppo.config import settings
from ppo.data.ais_client import AISClient
from ppo.data.cruise_schedule import CruiseScheduleClient
from ppo.data.nordpool_client import NordpoolClient
from ppo.data.scada_client import SCADAClient
from ppo.storage.database import SessionLocal, init_db
from ppo.storage.repositories import (
    AuditLogRepo,
    BESSStateRepo,
    LeaseRepo,
    ShedEventRepo,
    TenantRepo,
)

logger = logging.getLogger("ppo")

_scheduler: BackgroundScheduler | None = None


def _engine_tick() -> None:
    """Background job: run one orchestration cycle."""
    from ppo.core.bess_controller import BESSController
    from ppo.core.capacity_forecaster import CapacityForecaster
    from ppo.core.lease_manager import LeaseManager
    from ppo.core.load_shedding import LoadSheddingEngine
    from ppo.core.priority_engine import PriorityEngine

    ais = deps.get_ais()
    scada = deps.get_scada()
    nordpool = deps.get_nordpool()
    schedule = deps.get_schedule()

    session = SessionLocal()
    try:
        lease_repo = LeaseRepo(session)
        tenant_repo = TenantRepo(session)
        shed_repo = ShedEventRepo(session)
        bess_repo = BESSStateRepo(session)
        audit_repo = AuditLogRepo(session)

        forecaster = CapacityForecaster(scada, schedule, ais)
        lease_mgr = LeaseManager(forecaster, lease_repo, tenant_repo, audit_repo)
        shedding = LoadSheddingEngine(
            scada, ais, schedule, lease_repo, shed_repo, audit_repo
        )
        bess_ctrl = BESSController(ais, nordpool, bess_repo, audit_repo)

        engine = PriorityEngine(
            forecaster, lease_mgr, shedding, bess_ctrl, scada, audit_repo
        )
        state = engine.tick()
        session.commit()
        logger.info(
            "Tick complete: shed_mw=%.2f committed_mw=%.2f",
            state.shed_plan.total_shed_mw,
            state.committed_tenant_mw,
        )
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.exception("Engine tick failed: %s", exc)
    finally:
        session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _scheduler

    logger.info("Initialising database...")
    init_db()

    logger.info("Wiring data clients (simulated)...")
    ais = AISClient()
    nordpool = NordpoolClient()
    schedule = CruiseScheduleClient()
    # Close the SCADA/tenant-load loop via a callable that reads from DB.
    scada = SCADAClient()

    def _tenant_load_at(ts):
        sess = SessionLocal()
        try:
            total = sum(
                l.reserved_mw for l in LeaseRepo(sess).active_at(ts)
            )
            return total
        finally:
            sess.close()

    scada.set_tenant_load_fn(_tenant_load_at)
    deps.set_data_clients(ais=ais, scada=scada, nordpool=nordpool, schedule=schedule)

    logger.info("Starting scheduler...")
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _engine_tick,
        trigger=IntervalTrigger(minutes=settings.forecast_refresh_minutes),
        id="engine_tick",
        replace_existing=True,
    )
    _scheduler.start()

    yield

    logger.info("Shutting down scheduler...")
    if _scheduler:
        _scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = FastAPI(
        title="Port Power Orchestrator",
        description=(
            "Intelligent energy management for Copenhagen Malmö Port's "
            "shore power infrastructure."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )

    app.include_router(dashboard.router)
    app.include_router(system.router)
    app.include_router(tenants.router)
    app.include_router(leases.router)
    app.include_router(capacity.router)
    app.include_router(events.router)
    app.include_router(bess.router)

    return app


app = create_app()

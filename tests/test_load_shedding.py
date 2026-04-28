"""Tests for the load shedding engine."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ppo.core.load_shedding import LoadSheddingEngine, ShedReason
from ppo.data.ais_client import AISClient, VesselArrival
from ppo.data.cruise_schedule import CruiseScheduleClient
from ppo.data.scada_client import SCADAClient
from ppo.storage.models import AssetType, LeaseStatus
from ppo.storage.repositories import (
    AuditLogRepo,
    LeaseRepo,
    ShedEventRepo,
    TenantRepo,
)


def _engine(db_session, now, ais: AISClient | None = None):
    scada = SCADAClient(grid_capacity_mw=20.0)

    def _live_tenant_load(ts):
        return sum(l.reserved_mw for l in LeaseRepo(db_session).active_at(ts))

    scada.set_tenant_load_fn(_live_tenant_load)
    ais = ais or AISClient(now=now)
    schedule = CruiseScheduleClient()
    return LoadSheddingEngine(
        scada=scada,
        ais=ais,
        schedule=schedule,
        lease_repo=LeaseRepo(db_session),
        shed_event_repo=ShedEventRepo(db_session),
        audit_repo=AuditLogRepo(db_session),
        grid_capacity_mw=20.0,
        safety_margin_mw=1.5,
        ais_lookahead_hours=2.0,
    )


def _make_active_lease(db_session, tenant_id, mw, now, asset=AssetType.TRUCK_CHARGER):
    lease_repo = LeaseRepo(db_session)
    lease = lease_repo.create(
        tenant_id=tenant_id,
        asset_type=asset,
        asset_identifier=f"bay-{mw}",
        reserved_mw=mw,
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=4),
    )
    lease.status = LeaseStatus.ACTIVE
    db_session.flush()
    return lease


def test_no_shed_when_capacity_ample(tenant, db_session, fixed_now):
    now = datetime(2026, 1, 15, 3, 0)  # winter night, no cruise
    _make_active_lease(db_session, tenant.id, 2.0, now)
    engine = _engine(db_session, now)
    plan = engine.evaluate(now=now)
    assert plan.is_empty


def test_imminent_cruise_triggers_shed(tenant, db_session):
    now = datetime(2026, 6, 15, 6, 30)  # 30 minutes before arrival
    ais = AISClient(now=now)
    ais.schedule(
        VesselArrival(
            mmsi="211000001",
            name="TestShip",
            eta=now + timedelta(minutes=30),
            distance_nm=10,
            ops_capable=True,
            estimated_load_mw=12.0,
            berth="Oceankaj-T1",
        )
    )
    _make_active_lease(db_session, tenant.id, 5.0, now)
    _make_active_lease(db_session, tenant.id, 3.0, now, asset=AssetType.BESS)
    engine = _engine(db_session, now, ais=ais)
    plan = engine.evaluate(now=now)
    assert not plan.is_empty
    assert plan.trigger == ShedReason.AIS_ARRIVAL
    assert plan.total_shed_mw > 0


def test_shed_prefers_truck_loads_before_bess(tenant, db_session):
    """Order: trucks shed before BESS, so BESS can help as emergency discharge."""
    now = datetime(2026, 6, 15, 6, 30)
    ais = AISClient(now=now)
    ais.schedule(
        VesselArrival(
            mmsi="211000001",
            name="TestShip",
            eta=now + timedelta(minutes=30),
            distance_nm=10,
            ops_capable=True,
            estimated_load_mw=15.0,
            berth="Oceankaj-T1",
        )
    )
    truck = _make_active_lease(db_session, tenant.id, 5.0, now,
                               asset=AssetType.TRUCK_CHARGER)
    bess = _make_active_lease(db_session, tenant.id, 3.0, now,
                              asset=AssetType.BESS)
    engine = _engine(db_session, now, ais=ais)
    plan = engine.evaluate(now=now)
    assert plan.decisions, "expected shed decisions"
    # Truck lease should appear first in the ordered decisions
    assert plan.decisions[0].lease_id == truck.id


def test_execute_persists_shed_event_and_updates_lease(tenant, db_session):
    now = datetime(2026, 6, 15, 6, 30)
    ais = AISClient(now=now)
    ais.schedule(
        VesselArrival(
            mmsi="211000001",
            name="TestShip",
            eta=now + timedelta(minutes=30),
            distance_nm=10,
            ops_capable=True,
            estimated_load_mw=15.0,
            berth="Oceankaj-T1",
        )
    )
    lease = _make_active_lease(db_session, tenant.id, 5.0, now,
                               asset=AssetType.TRUCK_CHARGER)
    engine = _engine(db_session, now, ais=ais)
    plan = engine.evaluate(now=now)
    engine.execute(plan)
    db_session.flush()

    # Lease should be curtailed (or reduced)
    updated = LeaseRepo(db_session).get(lease.id)
    assert updated.reserved_mw < 5.0

    # Shed event should be recorded
    events = ShedEventRepo(db_session).all()
    assert len(events) >= 1
    assert events[0].mw_shed > 0


def test_headroom_safety_margin_respected(tenant, db_session):
    """Even without a ship, if tenant load approaches capacity - margin, shed fires."""
    # Late evening in June: cruise load winds down but not zero. Set a scenario
    # where tenant load is near grid_capacity - safety_margin.
    now = datetime(2026, 6, 15, 22, 0)  # late evening
    # Heavy overbook: tenant claims near full capacity while some cruise remains
    _make_active_lease(db_session, tenant.id, 18.0, now)
    engine = _engine(db_session, now)
    plan = engine.evaluate(now=now)
    assert not plan.is_empty

"""Tests for the lease manager."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ppo.core.capacity_forecaster import CapacityForecaster
from ppo.core.lease_manager import LeaseManager, LeaseRequest, QuoteDecision
from ppo.data.ais_client import AISClient
from ppo.data.cruise_schedule import CruiseScheduleClient
from ppo.data.scada_client import SCADAClient
from ppo.storage.models import AssetType, LeaseStatus


def _manager(db_session, now):
    from ppo.storage.repositories import AuditLogRepo, LeaseRepo, TenantRepo
    scada = SCADAClient(grid_capacity_mw=20.0)
    schedule = CruiseScheduleClient()
    ais = AISClient(now=now)
    fc = CapacityForecaster(scada, schedule, ais,
                            grid_capacity_mw=20.0, safety_margin_mw=1.5)
    return LeaseManager(
        fc,
        LeaseRepo(db_session),
        TenantRepo(db_session),
        AuditLogRepo(db_session),
    )


def test_quote_unknown_tenant(db_session, fixed_now):
    mgr = _manager(db_session, fixed_now)
    req = LeaseRequest(
        tenant_id=999,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=fixed_now,
        end_time=fixed_now + timedelta(hours=8),
    )
    quote = mgr.quote(req)
    assert quote.decision == QuoteDecision.UNAVAILABLE
    assert "Tenant" in quote.reason


def test_quote_available_when_capacity_abundant(tenant, db_session, fixed_now):
    mgr = _manager(db_session, fixed_now)
    req = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=fixed_now,
        end_time=fixed_now + timedelta(hours=6),
    )
    quote = mgr.quote(req)
    assert quote.decision == QuoteDecision.AVAILABLE
    assert quote.approved_mw == 1.5
    assert quote.price_dkk > 0


def test_book_creates_active_lease_if_in_window(tenant, db_session, fixed_now):
    """If start_time <= now <= end_time at book time, status becomes ACTIVE."""
    from ppo.storage.repositories import LeaseRepo
    mgr = _manager(db_session, datetime.now())
    now = datetime.now()
    req = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=now - timedelta(minutes=30),
        end_time=now + timedelta(hours=4),
    )
    lease, quote = mgr.book(req)
    assert lease is not None
    assert quote.decision == QuoteDecision.AVAILABLE
    assert lease.status == LeaseStatus.ACTIVE


def test_book_future_lease_is_pending(tenant, db_session):
    mgr = _manager(db_session, datetime.now())
    now = datetime.now()
    req = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=now + timedelta(hours=6),
        end_time=now + timedelta(hours=14),
    )
    lease, _ = mgr.book(req)
    assert lease is not None
    assert lease.status == LeaseStatus.PENDING


def test_overlapping_leases_consume_capacity(tenant, db_session, fixed_now):
    """Second tenant booking should see reduced effective capacity."""
    mgr = _manager(db_session, datetime.now())
    now = datetime.now()

    # First booking takes a big chunk
    req1 = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=10.0,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=5),
    )
    lease1, _ = mgr.book(req1)
    assert lease1 is not None

    # Second booking that overlaps same window
    req2 = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-02",
        requested_mw=10.0,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=4),
    )
    quote2 = mgr.quote(req2)
    # Second quote should see less than the full 20 MW because 10 is committed
    assert quote2.min_leasable_mw_in_window < 20.0


def test_cancel_sets_status_to_cancelled(tenant, db_session, fixed_now):
    mgr = _manager(db_session, datetime.now())
    now = datetime.now()
    req = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=5),
    )
    lease, _ = mgr.book(req)
    cancelled = mgr.cancel(lease.id, reason="test")
    assert cancelled.status == LeaseStatus.CANCELLED


def test_pricing_is_positive_and_scales_with_duration(tenant, db_session):
    mgr = _manager(db_session, datetime.now())
    now = datetime.now()
    short = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=3),
    )
    long = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=11),
    )
    q_short = mgr.quote(short)
    q_long = mgr.quote(long)
    assert q_short.price_dkk > 0
    assert q_long.price_dkk > q_short.price_dkk


def test_all_leases_are_interruptible_by_default(tenant, db_session):
    mgr = _manager(db_session, datetime.now())
    now = datetime.now()
    req = LeaseRequest(
        tenant_id=tenant.id,
        asset_type=AssetType.TRUCK_CHARGER,
        asset_identifier="bay-01",
        requested_mw=1.5,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=5),
    )
    lease, _ = mgr.book(req)
    assert lease.interruptible is True

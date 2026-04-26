"""Repository layer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ppo.storage.models import (
    AssetType,
    AuditLog,
    BESSMode,
    BESSState,
    CapacityForecast,
    Lease,
    LeaseStatus,
    ShedEvent,
    ShedTrigger,
    Tenant,
)


class TenantRepo:
    def __init__(self, session: Session):
        self.s = session

    def create(
        self, name: str, license_number: str, contact_email: str
    ) -> Tenant:
        t = Tenant(
            name=name,
            license_number=license_number,
            contact_email=contact_email,
        )
        self.s.add(t)
        self.s.flush()
        return t

    def get(self, tenant_id: int) -> Tenant | None:
        return self.s.get(Tenant, tenant_id)

    def by_name(self, name: str) -> Tenant | None:
        return self.s.execute(
            select(Tenant).where(Tenant.name == name)
        ).scalar_one_or_none()

    def all(self) -> list[Tenant]:
        return list(self.s.execute(select(Tenant)).scalars())

    def active(self) -> list[Tenant]:
        return list(
            self.s.execute(select(Tenant).where(Tenant.active.is_(True))).scalars()
        )


class LeaseRepo:
    def __init__(self, session: Session):
        self.s = session

    def create(
        self,
        tenant_id: int,
        asset_type: AssetType,
        asset_identifier: str,
        reserved_mw: float,
        start_time: datetime,
        end_time: datetime,
        price_dkk: float = 0.0,
    ) -> Lease:
        lease = Lease(
            tenant_id=tenant_id,
            asset_type=asset_type,
            asset_identifier=asset_identifier,
            reserved_mw=reserved_mw,
            start_time=start_time,
            end_time=end_time,
            price_dkk=price_dkk,
            status=LeaseStatus.PENDING,
            interruptible=True,
        )
        self.s.add(lease)
        self.s.flush()
        return lease

    def get(self, lease_id: int) -> Lease | None:
        return self.s.get(Lease, lease_id)

    def all(self) -> list[Lease]:
        return list(self.s.execute(select(Lease)).scalars())

    def active_at(self, timestamp: datetime) -> list[Lease]:
        stmt = select(Lease).where(
            and_(
                Lease.start_time <= timestamp,
                Lease.end_time >= timestamp,
                Lease.status.in_([LeaseStatus.ACTIVE, LeaseStatus.CURTAILED]),
            )
        )
        return list(self.s.execute(stmt).scalars())

    def overlapping(
        self, start: datetime, end: datetime
    ) -> list[Lease]:
        stmt = select(Lease).where(
            and_(
                Lease.end_time >= start,
                Lease.start_time <= end,
                Lease.status.notin_(
                    [LeaseStatus.CANCELLED, LeaseStatus.COMPLETED]
                ),
            )
        )
        return list(self.s.execute(stmt).scalars())

    def by_tenant(self, tenant_id: int) -> list[Lease]:
        stmt = select(Lease).where(Lease.tenant_id == tenant_id).order_by(
            Lease.start_time.desc()
        )
        return list(self.s.execute(stmt).scalars())

    def by_status(self, status: LeaseStatus) -> list[Lease]:
        return list(
            self.s.execute(select(Lease).where(Lease.status == status)).scalars()
        )

    def update_status(self, lease_id: int, status: LeaseStatus) -> Lease | None:
        lease = self.get(lease_id)
        if lease:
            lease.status = status
            self.s.flush()
        return lease


class ForecastRepo:
    def __init__(self, session: Session):
        self.s = session

    def save_many(self, forecasts: Iterable[CapacityForecast]) -> None:
        for f in forecasts:
            self.s.add(f)
        self.s.flush()

    def latest_for(self, target: datetime) -> CapacityForecast | None:
        stmt = (
            select(CapacityForecast)
            .where(CapacityForecast.target_time == target)
            .order_by(CapacityForecast.generated_at.desc())
            .limit(1)
        )
        return self.s.execute(stmt).scalar_one_or_none()

    def window(self, start: datetime, end: datetime) -> list[CapacityForecast]:
        stmt = (
            select(CapacityForecast)
            .where(
                and_(
                    CapacityForecast.target_time >= start,
                    CapacityForecast.target_time <= end,
                )
            )
            .order_by(CapacityForecast.target_time)
        )
        forecasts: dict[datetime, CapacityForecast] = {}
        for f in self.s.execute(stmt).scalars():
            existing = forecasts.get(f.target_time)
            if not existing or f.generated_at > existing.generated_at:
                forecasts[f.target_time] = f
        return [forecasts[k] for k in sorted(forecasts.keys())]


class ShedEventRepo:
    def __init__(self, session: Session):
        self.s = session

    def record(
        self,
        trigger: ShedTrigger,
        reason: str,
        mw_shed: float,
        response_time_seconds: float = 0.0,
        affected_lease_id: int | None = None,
    ) -> ShedEvent:
        ev = ShedEvent(
            trigger=trigger,
            reason=reason,
            mw_shed=mw_shed,
            response_time_seconds=response_time_seconds,
            affected_lease_id=affected_lease_id,
            completed_at=datetime.utcnow(),
        )
        self.s.add(ev)
        self.s.flush()
        return ev

    def recent(self, hours: int = 24) -> list[ShedEvent]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = (
            select(ShedEvent)
            .where(ShedEvent.triggered_at >= cutoff)
            .order_by(ShedEvent.triggered_at.desc())
        )
        return list(self.s.execute(stmt).scalars())

    def all(self) -> list[ShedEvent]:
        stmt = select(ShedEvent).order_by(ShedEvent.triggered_at.desc())
        return list(self.s.execute(stmt).scalars())


class BESSStateRepo:
    def __init__(self, session: Session):
        self.s = session

    def record(
        self,
        state_of_charge: float,
        mode: BESSMode,
        power_mw: float = 0.0,
        timestamp: datetime | None = None,
    ) -> BESSState:
        state = BESSState(
            state_of_charge=state_of_charge,
            mode=mode,
            power_mw=power_mw,
            timestamp=timestamp or datetime.utcnow(),
        )
        self.s.add(state)
        self.s.flush()
        return state

    def latest(self) -> BESSState | None:
        stmt = select(BESSState).order_by(BESSState.timestamp.desc()).limit(1)
        return self.s.execute(stmt).scalar_one_or_none()

    def history(self, hours: int = 24) -> list[BESSState]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = (
            select(BESSState)
            .where(BESSState.timestamp >= cutoff)
            .order_by(BESSState.timestamp)
        )
        return list(self.s.execute(stmt).scalars())


class AuditLogRepo:
    def __init__(self, session: Session):
        self.s = session

    def log(
        self,
        category: str,
        actor: str,
        message: str,
        metadata: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            category=category,
            actor=actor,
            message=message,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        self.s.add(entry)
        self.s.flush()
        return entry

    def recent(self, hours: int = 24, category: str | None = None) -> list[AuditLog]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = select(AuditLog).where(AuditLog.timestamp >= cutoff)
        if category:
            stmt = stmt.where(AuditLog.category == category)
        stmt = stmt.order_by(AuditLog.timestamp.desc())
        return list(self.s.execute(stmt).scalars())
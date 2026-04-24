"""Lease Manager."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from ppo.config import settings
from ppo.core.capacity_forecaster import CapacityForecaster
from ppo.storage.models import AssetType, Lease, LeaseStatus, Tenant
from ppo.storage.repositories import LeaseRepo, TenantRepo, AuditLogRepo


class QuoteDecision(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass
class LeaseRequest:
    tenant_id: int
    asset_type: AssetType
    asset_identifier: str
    requested_mw: float
    start_time: datetime
    end_time: datetime

    @property
    def duration_hours(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 3600.0


@dataclass
class LeaseQuote:
    request: LeaseRequest
    decision: QuoteDecision
    approved_mw: float
    price_dkk: float
    min_leasable_mw_in_window: float
    reason: str = ""


class LeaseManager:
    def __init__(
        self,
        forecaster: CapacityForecaster,
        lease_repo: LeaseRepo,
        tenant_repo: TenantRepo,
        audit_repo: AuditLogRepo | None = None,
    ):
        self.forecaster = forecaster
        self.lease_repo = lease_repo
        self.tenant_repo = tenant_repo
        self.audit_repo = audit_repo

    def quote(self, request: LeaseRequest) -> LeaseQuote:
        tenant = self.tenant_repo.get(request.tenant_id)
        if not tenant or not tenant.active:
            return LeaseQuote(
                request=request,
                decision=QuoteDecision.UNAVAILABLE,
                approved_mw=0.0,
                price_dkk=0.0,
                min_leasable_mw_in_window=0.0,
                reason="Tenant not found or inactive.",
            )

        min_leasable = self._min_leasable_across_window(request)

        committed = self._committed_mw_in_window(request.start_time, request.end_time)
        effective_leasable = max(0.0, min_leasable - committed)

        if effective_leasable >= request.requested_mw:
            price = self._price(request, request.requested_mw)
            return LeaseQuote(
                request=request,
                decision=QuoteDecision.AVAILABLE,
                approved_mw=request.requested_mw,
                price_dkk=price,
                min_leasable_mw_in_window=effective_leasable,
                reason="Capacity available across the full window.",
            )

        if effective_leasable <= 0:
            return LeaseQuote(
                request=request,
                decision=QuoteDecision.UNAVAILABLE,
                approved_mw=0.0,
                price_dkk=0.0,
                min_leasable_mw_in_window=effective_leasable,
                reason="No capacity available in the requested window.",
            )

        approved = round(effective_leasable, 2)
        price = self._price(request, approved)
        return LeaseQuote(
            request=request,
            decision=QuoteDecision.PARTIAL,
            approved_mw=approved,
            price_dkk=price,
            min_leasable_mw_in_window=effective_leasable,
            reason=f"Only {approved:.2f} MW available (requested {request.requested_mw:.2f}).",
        )

    def book(
        self, request: LeaseRequest, now: datetime | None = None
    ) -> tuple[Lease | None, LeaseQuote]:
        quote = self.quote(request)
        if quote.decision == QuoteDecision.UNAVAILABLE:
            return None, quote

        lease = self.lease_repo.create(
            tenant_id=request.tenant_id,
            asset_type=request.asset_type,
            asset_identifier=request.asset_identifier,
            reserved_mw=quote.approved_mw,
            start_time=request.start_time,
            end_time=request.end_time,
            price_dkk=quote.price_dkk,
        )
        reference = now or datetime.now()
        if request.start_time <= reference <= request.end_time:
            lease.status = LeaseStatus.ACTIVE
        else:
            lease.status = LeaseStatus.PENDING

        if self.audit_repo:
            self.audit_repo.log(
                category="lease.booked",
                actor=f"tenant:{request.tenant_id}",
                message=(
                    f"Booked {quote.approved_mw:.2f} MW "
                    f"{request.start_time:%Y-%m-%d %H:%M} - "
                    f"{request.end_time:%H:%M} "
                    f"({request.asset_type.value})"
                ),
                metadata={
                    "lease_id": lease.id,
                    "price_dkk": quote.price_dkk,
                    "decision": quote.decision.value,
                },
            )

        return lease, quote

    def cancel(self, lease_id: int, reason: str = "") -> Lease | None:
        lease = self.lease_repo.update_status(lease_id, LeaseStatus.CANCELLED)
        if lease and self.audit_repo:
            self.audit_repo.log(
                category="lease.cancelled",
                actor=f"tenant:{lease.tenant_id}",
                message=f"Lease {lease_id} cancelled. {reason}",
                metadata={"lease_id": lease_id},
            )
        return lease

    def activate_due(self, now: datetime | None = None) -> list[Lease]:
        now = now or datetime.now()
        activated: list[Lease] = []
        for lease in self.lease_repo.by_status(LeaseStatus.PENDING):
            if lease.start_time <= now <= lease.end_time:
                lease.status = LeaseStatus.ACTIVE
                activated.append(lease)
        return activated

    def complete_expired(self, now: datetime | None = None) -> list[Lease]:
        now = now or datetime.now()
        completed: list[Lease] = []
        for lease in self.lease_repo.all():
            if (
                lease.status in (LeaseStatus.ACTIVE, LeaseStatus.CURTAILED)
                and lease.end_time < now
            ):
                lease.status = LeaseStatus.COMPLETED
                completed.append(lease)
        return completed

    def _price(self, request: LeaseRequest, mw: float) -> float:
        hours_per_month = 30 * 24
        cap_rate_per_hour = settings.capacity_fee_dkk_mw_month / hours_per_month
        capacity_fee = mw * cap_rate_per_hour * request.duration_hours

        asset_fee = 0.0
        if request.asset_type == AssetType.TRUCK_CHARGER:
            per_hour = settings.truck_bay_lease_dkk_month / hours_per_month
            asset_fee = per_hour * request.duration_hours
        elif request.asset_type == AssetType.BESS:
            per_hour = (settings.bess_land_lease_dkk_year / 12) / hours_per_month
            asset_fee = per_hour * request.duration_hours

        return round(capacity_fee + asset_fee, 2)

    def _min_leasable_across_window(
        self, request: LeaseRequest, now: datetime | None = None
    ) -> float:
        reference = now or datetime.now()
        horizon = max(
            1,
            int(
                (request.end_time - reference).total_seconds() / 3600 + 1
            ),
        )
        summary = self.forecaster.forecast(horizon_hours=horizon, start=reference)
        relevant = [
            p
            for p in summary.points
            if request.start_time <= p.target_time <= request.end_time
        ]
        if not relevant:
            samples = []
            t = request.start_time.replace(minute=0, second=0, microsecond=0)
            while t <= request.end_time:
                samples.append(self.forecaster.at(t).leasable_mw)
                t += timedelta(hours=1)
            return min(samples) if samples else 0.0
        return min(p.leasable_mw for p in relevant)

    def _committed_mw_in_window(self, start: datetime, end: datetime) -> float:
        leases = self.lease_repo.overlapping(start, end)
        if not leases:
            return 0.0
        samples: list[float] = []
        t = start.replace(minute=0, second=0, microsecond=0)
        while t <= end:
            committed = sum(
                l.reserved_mw for l in leases if l.start_time <= t <= l.end_time
            )
            samples.append(committed)
            t += timedelta(hours=1)
        return max(samples) if samples else 0.0
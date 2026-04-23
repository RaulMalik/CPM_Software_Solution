"""Load Shedding Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from ppo.config import settings
from ppo.data.ais_client import AISClient, VesselArrival
from ppo.data.cruise_schedule import CruiseScheduleClient
from ppo.data.scada_client import SCADAClient
from ppo.storage.models import AssetType, Lease, LeaseStatus, ShedTrigger
from ppo.storage.repositories import (
    AuditLogRepo,
    LeaseRepo,
    ShedEventRepo,
)


class ShedReason(str, Enum):
    AIS_ARRIVAL = "ais_arrival"
    DEMAND_SPIKE = "demand_spike"
    SCHEDULED_CRUISE = "scheduled_cruise"
    SAFETY_MARGIN = "safety_margin"
    NONE = "none"


@dataclass
class ShedDecision:
    lease_id: int
    asset_type: AssetType
    asset_identifier: str
    shed_mw: float
    reason: ShedReason
    rationale: str


@dataclass
class ShedPlan:
    evaluated_at: datetime
    trigger: ShedReason
    total_shed_mw: float
    decisions: list[ShedDecision] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.decisions or self.total_shed_mw == 0.0


class LoadSheddingEngine:
    def __init__(
        self,
        scada: SCADAClient,
        ais: AISClient,
        schedule: CruiseScheduleClient,
        lease_repo: LeaseRepo,
        shed_event_repo: ShedEventRepo,
        audit_repo: AuditLogRepo | None = None,
        grid_capacity_mw: float | None = None,
        safety_margin_mw: float | None = None,
        ais_lookahead_hours: float | None = None,
    ):
        self.scada = scada
        self.ais = ais
        self.schedule = schedule
        self.lease_repo = lease_repo
        self.shed_event_repo = shed_event_repo
        self.audit_repo = audit_repo
        self.grid_capacity_mw = grid_capacity_mw or settings.grid_capacity_mw
        self.safety_margin_mw = (
            safety_margin_mw
            if safety_margin_mw is not None
            else settings.shed_safety_margin_mw
        )
        self.ais_lookahead = (
            ais_lookahead_hours
            if ais_lookahead_hours is not None
            else settings.cruise_ais_detection_hours
        )

    def evaluate(self, now: datetime | None = None) -> ShedPlan:
        now = now or datetime.now()

        projected_cruise = self._projected_cruise_load(now)

        active_leases = self.lease_repo.active_at(now)
        committed_tenant_mw = sum(l.reserved_mw for l in active_leases)

        headroom = (
            self.grid_capacity_mw
            - self.safety_margin_mw
            - projected_cruise
        )
        overrun = committed_tenant_mw - headroom

        if overrun <= 0:
            return ShedPlan(
                evaluated_at=now,
                trigger=ShedReason.NONE,
                total_shed_mw=0.0,
            )

        reason = self._determine_reason(now, projected_cruise)

        decisions = self._select_leases_to_shed(
            active_leases, overrun, reason
        )

        return ShedPlan(
            evaluated_at=now,
            trigger=reason,
            total_shed_mw=round(sum(d.shed_mw for d in decisions), 2),
            decisions=decisions,
        )

    def execute(self, plan: ShedPlan) -> None:
        if plan.is_empty:
            return

        for decision in plan.decisions:
            lease = self.lease_repo.get(decision.lease_id)
            if not lease:
                continue

            if decision.shed_mw >= lease.reserved_mw:
                lease.status = LeaseStatus.CURTAILED
                lease.reserved_mw = 0.0
            else:
                lease.reserved_mw = round(
                    lease.reserved_mw - decision.shed_mw, 2
                )

            trigger = ShedTrigger(decision.reason.value)
            self.shed_event_repo.record(
                trigger=trigger,
                reason=decision.rationale,
                mw_shed=decision.shed_mw,
                affected_lease_id=decision.lease_id,
            )

            if self.audit_repo:
                self.audit_repo.log(
                    category="load_shedding.action",
                    actor="ppo.load_shedding",
                    message=(
                        f"Shed {decision.shed_mw:.2f} MW from lease "
                        f"{decision.lease_id} ({decision.asset_identifier}): "
                        f"{decision.rationale}"
                    ),
                    metadata={
                        "lease_id": decision.lease_id,
                        "reason": decision.reason.value,
                    },
                )

    def _projected_cruise_load(self, now: datetime) -> float:
        horizon = max(self.ais_lookahead * 3600, 3600)
        end = now + timedelta(seconds=horizon)

        live = self.scada.read(now).cruise_load_mw

        ais_contribution = 0.0
        for arr in self.ais.upcoming_arrivals(within_hours=self.ais_lookahead):
            if arr.ops_capable:
                ais_contribution += arr.estimated_load_mw

        scheduled_peak = 0.0
        t = now
        while t <= end:
            scheduled_peak = max(scheduled_peak, self.schedule.load_at(t))
            t += timedelta(minutes=15)

        return max(live, ais_contribution, scheduled_peak)

    def _determine_reason(
        self, now: datetime, projected_cruise: float
    ) -> ShedReason:
        imminent = self.ais.imminent_arrivals(within_hours=self.ais_lookahead)
        if imminent:
            return ShedReason.AIS_ARRIVAL

        scheduled = self.schedule.upcoming(window_hours=self.ais_lookahead)
        if scheduled:
            return ShedReason.SCHEDULED_CRUISE

        live = self.scada.read(now).cruise_load_mw
        if live > 0 and projected_cruise > live * 1.1:
            return ShedReason.DEMAND_SPIKE

        return ShedReason.SAFETY_MARGIN

    def _select_leases_to_shed(
        self,
        active_leases: list[Lease],
        overrun_mw: float,
        reason: ShedReason,
    ) -> list[ShedDecision]:
        candidates = [
            l for l in active_leases if l.interruptible and l.reserved_mw > 0
        ]

        priority_order = {
            AssetType.TRUCK_CHARGER: 0,
            AssetType.DATA_CENTRE: 1,
            AssetType.OTHER: 2,
            AssetType.BESS: 3,
        }
        candidates.sort(
            key=lambda l: (priority_order.get(l.asset_type, 99), -l.reserved_mw)
        )

        decisions: list[ShedDecision] = []
        remaining = overrun_mw
        for lease in candidates:
            if remaining <= 0:
                break
            shed = min(lease.reserved_mw, remaining)
            decisions.append(
                ShedDecision(
                    lease_id=lease.id,
                    asset_type=lease.asset_type,
                    asset_identifier=lease.asset_identifier,
                    shed_mw=round(shed, 2),
                    reason=reason,
                    rationale=(
                        f"Curtailing {shed:.2f} MW to protect cruise priority "
                        f"(reason: {reason.value})"
                    ),
                )
            )
            remaining -= shed

        return decisions
"""Priority Engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ppo.core.bess_controller import BESSController, BESSPlan
from ppo.core.capacity_forecaster import CapacityForecaster, ForecastSummary
from ppo.core.lease_manager import LeaseManager
from ppo.core.load_shedding import LoadSheddingEngine, ShedPlan
from ppo.data.scada_client import MeterReading, SCADAClient
from ppo.storage.repositories import AuditLogRepo


@dataclass
class SystemState:
    timestamp: datetime
    meter: MeterReading
    forecast_summary: ForecastSummary
    shed_plan: ShedPlan
    bess_plan: BESSPlan
    active_lease_count: int
    committed_tenant_mw: float


class PriorityEngine:
    def __init__(
        self,
        forecaster: CapacityForecaster,
        lease_manager: LeaseManager,
        shedding: LoadSheddingEngine,
        bess: BESSController,
        scada: SCADAClient,
        audit_repo: AuditLogRepo | None = None,
    ):
        self.forecaster = forecaster
        self.lease_manager = lease_manager
        self.shedding = shedding
        self.bess = bess
        self.scada = scada
        self.audit_repo = audit_repo

    def tick(self, now: datetime | None = None) -> SystemState:
        now = now or datetime.now()

        activated = self.lease_manager.activate_due(now=now)
        completed = self.lease_manager.complete_expired(now=now)

        forecast = self.forecaster.forecast()

        shed_plan = self.shedding.evaluate(now)
        if not shed_plan.is_empty:
            self.shedding.execute(shed_plan)

        bess_plan = self.bess.plan(horizon_hours=24, start=now)
        self.bess.execute_next(bess_plan)

        active_leases = self.lease_manager.lease_repo.active_at(now)
        committed = sum(l.reserved_mw for l in active_leases)
        meter = self.scada.read(now)

        if self.audit_repo:
            self.audit_repo.log(
                category="engine.tick",
                actor="ppo.priority_engine",
                message=(
                    f"Tick @ {now:%Y-%m-%d %H:%M}: "
                    f"activated={len(activated)} completed={len(completed)} "
                    f"shed_mw={shed_plan.total_shed_mw:.2f} "
                    f"committed_tenant_mw={committed:.2f}"
                ),
            )

        return SystemState(
            timestamp=now,
            meter=meter,
            forecast_summary=forecast,
            shed_plan=shed_plan,
            bess_plan=bess_plan,
            active_lease_count=len(active_leases),
            committed_tenant_mw=round(committed, 2),
        )
"""
Simulator for end-to-end PPO scenarios.

A Scenario scripts a concrete cruise arrival + tenant activity case and
walks the PriorityEngine through several ticks, recording the system
state at each step. Used for demo runs and the pitch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ppo.core.bess_controller import BESSController
from ppo.core.capacity_forecaster import CapacityForecaster
from ppo.core.lease_manager import LeaseManager, LeaseRequest
from ppo.core.load_shedding import LoadSheddingEngine
from ppo.core.priority_engine import PriorityEngine, SystemState
from ppo.data.ais_client import AISClient, VesselArrival
from ppo.data.cruise_schedule import CruiseCall, CruiseScheduleClient
from ppo.data.nordpool_client import NordpoolClient
from ppo.data.scada_client import SCADAClient
from ppo.storage.database import SessionLocal
from ppo.storage.models import AssetType
from ppo.storage.repositories import (
    AuditLogRepo,
    BESSStateRepo,
    LeaseRepo,
    ShedEventRepo,
    TenantRepo,
)


@dataclass
class Scenario:
    """A scripted simulation scenario."""

    name: str
    start_time: datetime
    duration_hours: float = 24.0
    tick_minutes: int = 15
    cruise_arrivals: list[VesselArrival] = field(default_factory=list)
    cruise_calls: list[CruiseCall] = field(default_factory=list)
    lease_requests: list[LeaseRequest] = field(default_factory=list)


@dataclass
class ScenarioResult:
    scenario_name: str
    states: list[SystemState]
    booked_leases: list[int]

    @property
    def total_shed_mw(self) -> float:
        return sum(s.shed_plan.total_shed_mw for s in self.states)

    @property
    def shed_events_count(self) -> int:
        return sum(1 for s in self.states if not s.shed_plan.is_empty)


class Simulator:
    """
    Runs a Scenario end-to-end against a fresh database session.

    The simulator builds its own data clients, wires them through the
    engine, and steps forward in ticks. Each tick records a ``SystemState``.
    """

    def __init__(self):
        self.session = SessionLocal()
        self._tenant_repo = TenantRepo(self.session)
        self._lease_repo = LeaseRepo(self.session)
        self._shed_repo = ShedEventRepo(self.session)
        self._bess_repo = BESSStateRepo(self.session)
        self._audit_repo = AuditLogRepo(self.session)

    def run(self, scenario: Scenario) -> ScenarioResult:
        # Data clients scoped to this scenario
        ais = AISClient(now=scenario.start_time)
        for arrival in scenario.cruise_arrivals:
            ais.schedule(arrival)

        nordpool = NordpoolClient()
        schedule = CruiseScheduleClient()
        for call in scenario.cruise_calls:
            schedule.add_booking(call)

        scada = SCADAClient()
        scada.set_tenant_load_fn(self._live_tenant_load)

        # Core wiring
        forecaster = CapacityForecaster(scada, schedule, ais)
        lease_mgr = LeaseManager(
            forecaster, self._lease_repo, self._tenant_repo, self._audit_repo
        )
        shedding = LoadSheddingEngine(
            scada,
            ais,
            schedule,
            self._lease_repo,
            self._shed_repo,
            self._audit_repo,
        )
        bess = BESSController(ais, nordpool, self._bess_repo, self._audit_repo)
        engine = PriorityEngine(
            forecaster, lease_mgr, shedding, bess, scada, self._audit_repo
        )

        # Place the scenario's lease requests (before ticking)
        booked_ids: list[int] = []
        for req in scenario.lease_requests:
            lease, _ = lease_mgr.book(req, now=scenario.start_time)
            if lease:
                booked_ids.append(lease.id)

        self.session.commit()

        # Step through ticks
        states: list[SystemState] = []
        ticks = int(scenario.duration_hours * 60 / scenario.tick_minutes) + 1
        now = scenario.start_time
        for _ in range(ticks):
            state = engine.tick(now=now)
            states.append(state)
            self.session.commit()
            now += timedelta(minutes=scenario.tick_minutes)

        return ScenarioResult(
            scenario_name=scenario.name,
            states=states,
            booked_leases=booked_ids,
        )

    def _live_tenant_load(self, timestamp: datetime) -> float:
        # SQLAlchemy session is shared with the engine via commit between ticks
        try:
            active = self._lease_repo.active_at(timestamp)
            return sum(l.reserved_mw for l in active)
        except Exception:
            return 0.0

    def close(self) -> None:
        self.session.close()

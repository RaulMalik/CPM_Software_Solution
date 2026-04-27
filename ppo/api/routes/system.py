"""System-wide status + manual engine tick."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ppo.api.deps import (
    get_bess_state_repo,
    get_forecaster,
    get_lease_repo,
    get_priority_engine,
    get_scada,
    get_shed_event_repo,
)
from ppo.api.schemas import (
    BESSStateOut,
    ForecastPointOut,
    ForecastSummaryOut,
    MeterReadingOut,
    ShedEventOut,
    SystemStatusOut,
)
from ppo.core.capacity_forecaster import CapacityForecaster
from ppo.core.priority_engine import PriorityEngine
from ppo.data.scada_client import SCADAClient
from ppo.storage.repositories import BESSStateRepo, LeaseRepo, ShedEventRepo

router = APIRouter(tags=["system"])


@router.get("/status", response_model=SystemStatusOut)
def status(
    scada: SCADAClient = Depends(get_scada),
    lease_repo: LeaseRepo = Depends(get_lease_repo),
    bess_repo: BESSStateRepo = Depends(get_bess_state_repo),
    shed_repo: ShedEventRepo = Depends(get_shed_event_repo),
    forecaster: CapacityForecaster = Depends(get_forecaster),
):
    from datetime import datetime

    now = datetime.now()
    reading = scada.read(now)
    active = lease_repo.active_at(now)
    summary = forecaster.forecast()
    latest_bess = bess_repo.latest()
    recent_shed = shed_repo.recent(hours=24)

    return SystemStatusOut(
        timestamp=now,
        meter=MeterReadingOut(
            timestamp=reading.timestamp,
            cruise_load_mw=round(reading.cruise_load_mw, 2),
            tenant_load_mw=round(reading.tenant_load_mw, 2),
            grid_capacity_mw=reading.grid_capacity_mw,
            idle_mw=round(reading.idle_mw, 2),
            utilisation=round(reading.utilisation, 3),
        ),
        active_lease_count=len(active),
        committed_tenant_mw=round(sum(l.reserved_mw for l in active), 2),
        forecast_summary=ForecastSummaryOut(
            horizon_hours=summary.horizon_hours,
            generated_at=summary.generated_at,
            total_leasable_mwh=round(summary.total_leasable_mwh, 2),
            peak_leasable_mw=round(summary.peak_leasable_mw, 2),
            min_leasable_mw=round(summary.min_leasable_mw, 2),
            avg_leasable_mw=round(summary.avg_leasable_mw, 2),
            points=[
                ForecastPointOut(
                    target_time=p.target_time,
                    predicted_cruise_mw=p.predicted_cruise_mw,
                    predicted_idle_mw=p.predicted_idle_mw,
                    leasable_mw=p.leasable_mw,
                    confidence=p.confidence,
                )
                for p in summary.points[:24]
            ],
        ),
        latest_bess=BESSStateOut.model_validate(latest_bess) if latest_bess else None,
        recent_shed_events=[ShedEventOut.model_validate(e) for e in recent_shed],
    )


@router.post("/tick")
def manual_tick(engine: PriorityEngine = Depends(get_priority_engine)):
    """Trigger one orchestration cycle manually (useful for demos)."""
    state = engine.tick()
    return {
        "timestamp": state.timestamp,
        "active_leases": state.active_lease_count,
        "committed_tenant_mw": state.committed_tenant_mw,
        "shed_mw": state.shed_plan.total_shed_mw,
        "shed_trigger": state.shed_plan.trigger.value,
        "bess_next_action": (
            state.bess_plan.next_action.action.value
            if state.bess_plan.next_action
            else None
        ),
    }

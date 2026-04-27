"""Capacity forecast query routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ppo.api.deps import get_forecaster
from ppo.api.schemas import ForecastPointOut, ForecastSummaryOut
from ppo.core.capacity_forecaster import CapacityForecaster

router = APIRouter(prefix="/capacity", tags=["capacity"])


@router.get("/forecast", response_model=ForecastSummaryOut)
def forecast(
    horizon_hours: int = Query(72, ge=1, le=168),
    forecaster: CapacityForecaster = Depends(get_forecaster),
):
    summary = forecaster.forecast(horizon_hours=horizon_hours)
    return ForecastSummaryOut(
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
            for p in summary.points
        ],
    )

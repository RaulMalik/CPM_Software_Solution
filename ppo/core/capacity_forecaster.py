"""Capacity Forecaster."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

from ppo.config import settings
from ppo.data.ais_client import AISClient, VesselArrival
from ppo.data.cruise_schedule import CruiseScheduleClient
from ppo.data.scada_client import SCADAClient


@dataclass(frozen=True)
class ForecastPoint:
    target_time: datetime
    predicted_cruise_mw: float
    predicted_idle_mw: float
    leasable_mw: float
    confidence: float


@dataclass
class ForecastSummary:
    horizon_hours: int
    generated_at: datetime
    points: list[ForecastPoint]

    @property
    def total_leasable_mwh(self) -> float:
        return sum(p.leasable_mw for p in self.points)

    @property
    def peak_leasable_mw(self) -> float:
        return max((p.leasable_mw for p in self.points), default=0.0)

    @property
    def min_leasable_mw(self) -> float:
        return min((p.leasable_mw for p in self.points), default=0.0)

    @property
    def avg_leasable_mw(self) -> float:
        return (
            sum(p.leasable_mw for p in self.points) / len(self.points)
            if self.points
            else 0.0
        )


class CapacityForecaster:
    def __init__(
        self,
        scada: SCADAClient,
        schedule: CruiseScheduleClient,
        ais: AISClient,
        grid_capacity_mw: float | None = None,
        safety_margin_mw: float | None = None,
    ):
        self.scada = scada
        self.schedule = schedule
        self.ais = ais
        self.grid_capacity_mw = grid_capacity_mw or settings.grid_capacity_mw
        self.safety_margin_mw = (
            safety_margin_mw
            if safety_margin_mw is not None
            else settings.shed_safety_margin_mw
        )

    def forecast(
        self,
        horizon_hours: int | None = None,
        start: datetime | None = None,
    ) -> ForecastSummary:
        horizon = horizon_hours or settings.forecast_horizon_hours
        start = (start or datetime.now()).replace(
            minute=0, second=0, microsecond=0
        )

        ais_arrivals = self.ais.upcoming_arrivals(within_hours=horizon)

        points: list[ForecastPoint] = []
        for h in range(horizon):
            target = start + timedelta(hours=h)
            points.append(self._forecast_point(target, ais_arrivals))

        return ForecastSummary(
            horizon_hours=horizon,
            generated_at=datetime.now(),
            points=points,
        )

    def at(self, target_time: datetime) -> ForecastPoint:
        ais_arrivals = self.ais.upcoming_arrivals(
            within_hours=settings.cruise_ais_detection_hours
        )
        return self._forecast_point(target_time, ais_arrivals)

    def _forecast_point(
        self, target_time: datetime, ais_arrivals: Sequence[VesselArrival]
    ) -> ForecastPoint:
        cruise_from_schedule = self.schedule.load_at(target_time)
        cruise_from_historical = self.scada.expected_cruise_mw(target_time)
        cruise_from_ais = self._ais_contribution(target_time, ais_arrivals)

        predicted_cruise = max(
            cruise_from_schedule,
            cruise_from_historical,
            cruise_from_ais,
        )
        predicted_cruise = min(predicted_cruise, self.grid_capacity_mw)

        idle = max(0.0, self.grid_capacity_mw - predicted_cruise)
        leasable = max(0.0, idle - self.safety_margin_mw)

        confidence = self._confidence(
            cruise_from_schedule, cruise_from_historical, cruise_from_ais
        )

        return ForecastPoint(
            target_time=target_time,
            predicted_cruise_mw=round(predicted_cruise, 2),
            predicted_idle_mw=round(idle, 2),
            leasable_mw=round(leasable, 2),
            confidence=round(confidence, 2),
        )

    def _ais_contribution(
        self, target_time: datetime, arrivals: Sequence[VesselArrival]
    ) -> float:
        total = 0.0
        for a in arrivals:
            if a.ops_capable and a.eta <= target_time:
                total += a.estimated_load_mw
        return total

    def _confidence(
        self,
        from_schedule: float,
        from_historical: float,
        from_ais: float,
    ) -> float:
        sources = [from_schedule, from_historical, from_ais]
        non_zero = [s for s in sources if s > 0]
        if not non_zero:
            return 0.95
        spread = max(non_zero) - min(non_zero)
        peak = max(non_zero)
        if peak == 0:
            return 0.95
        return max(0.5, 1.0 - (spread / peak) * 0.5)
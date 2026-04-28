"""Tests for the capacity forecaster."""

from __future__ import annotations

from datetime import datetime, timedelta

from ppo.config import settings
from ppo.core.capacity_forecaster import CapacityForecaster
from ppo.data.ais_client import AISClient, VesselArrival
from ppo.data.cruise_schedule import CruiseCall, CruiseScheduleClient
from ppo.data.scada_client import SCADAClient


def _forecaster(now: datetime) -> CapacityForecaster:
    scada = SCADAClient(grid_capacity_mw=20.0)
    schedule = CruiseScheduleClient()
    ais = AISClient(now=now)
    return CapacityForecaster(
        scada=scada, schedule=schedule, ais=ais,
        grid_capacity_mw=20.0, safety_margin_mw=1.5,
    )


def test_forecast_produces_one_point_per_hour(fixed_now):
    fc = _forecaster(fixed_now)
    summary = fc.forecast(horizon_hours=24, start=fixed_now)
    assert len(summary.points) == 24
    # Hourly spacing
    diffs = [
        (summary.points[i + 1].target_time - summary.points[i].target_time)
        for i in range(len(summary.points) - 1)
    ]
    assert all(d == timedelta(hours=1) for d in diffs)


def test_leasable_never_negative(fixed_now):
    fc = _forecaster(fixed_now)
    summary = fc.forecast(horizon_hours=72, start=fixed_now)
    for p in summary.points:
        assert p.leasable_mw >= 0
        assert p.predicted_idle_mw >= 0
        assert p.predicted_cruise_mw >= 0


def test_idle_plus_cruise_fits_in_capacity(fixed_now):
    fc = _forecaster(fixed_now)
    summary = fc.forecast(horizon_hours=24, start=fixed_now)
    for p in summary.points:
        assert p.predicted_cruise_mw + p.predicted_idle_mw <= 20.0 + 1e-6


def test_winter_nights_are_fully_idle():
    winter_night = datetime(2026, 1, 15, 2, 0)
    fc = _forecaster(winter_night)
    point = fc.at(winter_night)
    assert point.predicted_cruise_mw == 0.0
    assert point.predicted_idle_mw == 20.0


def test_scheduled_cruise_reduces_leasable_capacity(fixed_now):
    scada = SCADAClient(grid_capacity_mw=20.0)
    schedule = CruiseScheduleClient()
    schedule.add_booking(
        CruiseCall(
            vessel_name="TestShip",
            mmsi="211000001",
            arrival=fixed_now,
            departure=fixed_now + timedelta(hours=12),
            berth="Oceankaj-T1",
            ops_capable=True,
            estimated_load_mw=8.0,
        )
    )
    ais = AISClient(now=fixed_now)
    fc = CapacityForecaster(scada=scada, schedule=schedule, ais=ais,
                            grid_capacity_mw=20.0, safety_margin_mw=1.5)
    point = fc.at(fixed_now + timedelta(hours=4))
    # Scheduled cruise load should propagate
    assert point.predicted_cruise_mw >= 8.0
    # Leasable is capacity minus cruise minus safety margin
    assert point.leasable_mw <= 20.0 - 8.0 - 1.5 + 1e-6


def test_ais_imminent_arrival_increases_predicted_cruise_load(fixed_now):
    scada = SCADAClient(grid_capacity_mw=20.0)
    schedule = CruiseScheduleClient()
    ais = AISClient(now=fixed_now)
    ais.schedule(
        VesselArrival(
            mmsi="211000002",
            name="AIS-Ship",
            eta=fixed_now + timedelta(hours=1),
            distance_nm=15.0,
            ops_capable=True,
            estimated_load_mw=10.0,
            berth="Oceankaj-T2",
        )
    )
    fc = CapacityForecaster(scada=scada, schedule=schedule, ais=ais,
                            grid_capacity_mw=20.0, safety_margin_mw=1.5)
    future_point = fc.at(fixed_now + timedelta(hours=2))
    assert future_point.predicted_cruise_mw >= 10.0


def test_confidence_score_in_valid_range(fixed_now):
    fc = _forecaster(fixed_now)
    summary = fc.forecast(horizon_hours=48, start=fixed_now)
    for p in summary.points:
        assert 0.0 <= p.confidence <= 1.0


def test_summary_aggregates_are_consistent(fixed_now):
    fc = _forecaster(fixed_now)
    summary = fc.forecast(horizon_hours=24, start=fixed_now)
    assert summary.peak_leasable_mw >= summary.avg_leasable_mw
    assert summary.avg_leasable_mw >= summary.min_leasable_mw
    assert summary.total_leasable_mwh >= summary.min_leasable_mw * 24 - 1e-6

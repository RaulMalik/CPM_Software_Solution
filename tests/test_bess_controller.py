"""Tests for the BESS controller."""

from __future__ import annotations

from datetime import datetime, timedelta

from ppo.core.bess_controller import BESSController, CommandAction
from ppo.data.ais_client import AISClient, VesselArrival
from ppo.data.nordpool_client import NordpoolClient
from ppo.storage.models import BESSMode
from ppo.storage.repositories import AuditLogRepo, BESSStateRepo


def _controller(db_session, ais=None):
    return BESSController(
        ais=ais or AISClient(),
        nordpool=NordpoolClient(),
        bess_state_repo=BESSStateRepo(db_session),
        audit_repo=AuditLogRepo(db_session),
    )


def test_initial_soc_defaults_to_half(db_session):
    ctrl = _controller(db_session)
    assert ctrl.current_soc() == 0.5


def test_plan_produces_requested_horizon(db_session):
    ctrl = _controller(db_session)
    plan = ctrl.plan(horizon_hours=12)
    assert len(plan.commands) == 12


def test_off_peak_hours_trigger_charging(db_session):
    """At 03:00 (off-peak), controller should charge."""
    ctrl = _controller(db_session)
    start = datetime(2026, 6, 15, 3, 0)
    plan = ctrl.plan(horizon_hours=1, start=start)
    cmd = plan.next_action
    assert cmd is not None
    assert cmd.action == CommandAction.CHARGE


def test_peak_hours_trigger_discharging(db_session):
    """At 18:00 (peak), controller should discharge."""
    ctrl = _controller(db_session)
    # Seed a high SoC so discharge is possible
    BESSStateRepo(db_session).record(
        state_of_charge=0.8, mode=BESSMode.IDLE, power_mw=0.0
    )
    db_session.flush()

    start = datetime(2026, 6, 15, 18, 0)
    plan = ctrl.plan(horizon_hours=1, start=start)
    cmd = plan.next_action
    assert cmd is not None
    assert cmd.action == CommandAction.DISCHARGE


def test_imminent_cruise_triggers_emergency_discharge(db_session):
    now = datetime(2026, 6, 15, 6, 30)
    ais = AISClient(now=now)
    ais.schedule(
        VesselArrival(
            mmsi="211000001",
            name="TestShip",
            eta=now + timedelta(minutes=20),
            distance_nm=5.0,
            ops_capable=True,
            estimated_load_mw=12.0,
            berth="Oceankaj-T1",
        )
    )
    # Start with some SoC so emergency discharge is allowed
    BESSStateRepo(db_session).record(
        state_of_charge=0.6, mode=BESSMode.CHARGING, power_mw=-4.0
    )
    db_session.flush()

    ctrl = _controller(db_session, ais=ais)
    plan = ctrl.plan(horizon_hours=1, start=now)
    cmd = plan.next_action
    assert cmd is not None
    assert cmd.action == CommandAction.EMERGENCY_DISCHARGE
    assert cmd.power_mw > 0


def test_execute_next_records_state(db_session):
    ctrl = _controller(db_session)
    start = datetime(2026, 6, 15, 3, 0)
    plan = ctrl.plan(horizon_hours=1, start=start)
    ctrl.execute_next(plan)
    latest = BESSStateRepo(db_session).latest()
    assert latest is not None
    assert latest.mode == BESSMode.CHARGING


def test_soc_stays_within_bounds(db_session):
    """Across a multi-hour plan, projected SoC never exceeds [min, max]."""
    from ppo.config import settings

    ctrl = _controller(db_session)
    plan = ctrl.plan(horizon_hours=48)
    # Execute each command sequentially
    soc = ctrl.current_soc()
    for cmd in plan.commands:
        soc = ctrl._apply_command_to_soc(soc, cmd)
        assert soc >= settings.bess_min_soc - 1e-6
        assert soc <= settings.bess_max_soc + 1e-6

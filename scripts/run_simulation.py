"""
End-to-end PPO simulation.

Scripts a realistic scenario:
- June morning in Copenhagen
- Overnight truck charging is active
- A cruise ship arrives at 07:00
- PPO should detect, shed tenant loads, and switch BESS to discharge

Generates visualisations used in the Demo Day pitch.

Usage:
    python -m scripts.run_simulation
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ppo.data.ais_client import VesselArrival
from ppo.data.cruise_schedule import CruiseCall
from ppo.core.lease_manager import LeaseRequest
from ppo.simulation.simulator import Scenario, Simulator
from ppo.simulation.visualizations import (
    plot_capacity_heatmap,
    plot_load_shedding,
    plot_revenue,
)
from ppo.storage.database import drop_db, init_db
from ppo.storage.models import AssetType
from ppo.storage.repositories import TenantRepo
from ppo.storage.database import SessionLocal


OUT_DIR = Path(__file__).resolve().parent.parent / "output"


def _ensure_tenant() -> int:
    """Make sure at least one tenant exists; return its ID."""
    session = SessionLocal()
    try:
        repo = TenantRepo(session)
        tenant = repo.by_name("Ørsted Flex")
        if not tenant:
            tenant = repo.create(
                name="Ørsted Flex",
                license_number="DK-EL-TRADER-2019-0147",
                contact_email="flex@orsted.dk",
            )
            session.commit()
        return tenant.id
    finally:
        session.close()


def _build_june_morning_scenario(tenant_id: int) -> Scenario:
    """Scenario: truck bays active overnight, cruise arrives at 07:00."""
    # Fixed June 2026 morning
    start = datetime(2026, 6, 15, 2, 0)

    cruise_arrival_time = start.replace(hour=7)
    cruise_departure_time = start.replace(hour=19)

    arrivals = [
        VesselArrival(
            mmsi="211987654",
            name="AIDAnova",
            eta=cruise_arrival_time,
            distance_nm=80.0,
            ops_capable=True,
            estimated_load_mw=12.0,
            berth="Oceankaj-T1",
        )
    ]

    cruise_calls = [
        CruiseCall(
            vessel_name="AIDAnova",
            mmsi="211987654",
            arrival=cruise_arrival_time,
            departure=cruise_departure_time,
            berth="Oceankaj-T1",
            ops_capable=True,
            estimated_load_mw=12.0,
        )
    ]

    # 4 truck bays active overnight, plus BESS charging
    lease_requests = [
        LeaseRequest(
            tenant_id=tenant_id,
            asset_type=AssetType.TRUCK_CHARGER,
            asset_identifier=f"bay-{i:02d}",
            requested_mw=1.5,
            start_time=start,
            end_time=start + timedelta(hours=6),  # ends at 08:00
        )
        for i in range(1, 5)
    ] + [
        LeaseRequest(
            tenant_id=tenant_id,
            asset_type=AssetType.BESS,
            asset_identifier="bess-t3",
            requested_mw=3.0,
            start_time=start,
            end_time=start + timedelta(hours=8),
        )
    ]

    return Scenario(
        name="June morning — cruise arrival at 07:00",
        start_time=start,
        duration_hours=10.0,
        tick_minutes=15,
        cruise_arrivals=arrivals,
        cruise_calls=cruise_calls,
        lease_requests=lease_requests,
    )


def _monthly_revenue_estimate() -> dict[str, float]:
    """Simple monthly revenue estimate for the pitch chart."""
    # Based on ppo_mvp_v3 numbers: leasable MW varies by month,
    # capacity fee 35,000 DKK/MW/month, plus fixed lease fees.
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    # Average leasable MW by month (from the heatmap)
    leasable_mw = [12.0, 12.0, 12.0, 11.9, 11.5, 10.9,
                   10.8, 10.9, 11.6, 11.9, 12.0, 11.8]
    fixed_fees = 12_000 * 10 + 600_000 / 12 + 480_000 / 12  # bays + BESS land + license
    return {
        m: mw * 35_000 * 0.60 + fixed_fees
        for m, mw in zip(months, leasable_mw)
    }


def main() -> None:
    print("=" * 60)
    print("  PPO End-to-End Simulation")
    print("=" * 60)

    # Fresh DB
    print("\n[1/4] Resetting database...")
    drop_db()
    init_db()

    print("[2/4] Creating tenant...")
    tenant_id = _ensure_tenant()

    print("[3/4] Running scenario...")
    scenario = _build_june_morning_scenario(tenant_id)
    sim = Simulator()
    try:
        result = sim.run(scenario)
    finally:
        sim.close()

    print(f"       Scenario: {result.scenario_name}")
    print(f"       Ticks recorded: {len(result.states)}")
    print(f"       Leases booked: {len(result.booked_leases)}")
    print(f"       Shed events: {result.shed_events_count}")
    print(f"       Total MW shed: {result.total_shed_mw:.2f}")

    print("[4/4] Generating visualisations...")
    OUT_DIR.mkdir(exist_ok=True)

    # Forecast heatmap (uses the scenario's forecaster output at a fresh tick)
    from ppo.data.ais_client import AISClient
    from ppo.data.cruise_schedule import CruiseScheduleClient
    from ppo.data.scada_client import SCADAClient
    from ppo.core.capacity_forecaster import CapacityForecaster

    ais = AISClient()
    scada = SCADAClient()
    schedule = CruiseScheduleClient()
    forecaster = CapacityForecaster(scada, schedule, ais)
    summary = forecaster.forecast(horizon_hours=72)
    heatmap_path = plot_capacity_heatmap(
        summary, OUT_DIR / "sim_01_capacity_heatmap.png"
    )
    print(f"       → {heatmap_path}")

    shed_path = plot_load_shedding(
        result,
        grid_capacity_mw=20.0,
        out=OUT_DIR / "sim_02_load_shedding.png",
    )
    print(f"       → {shed_path}")

    rev_path = plot_revenue(
        _monthly_revenue_estimate(),
        OUT_DIR / "sim_03_revenue.png",
    )
    print(f"       → {rev_path}")

    print("\nDone. Outputs in:", OUT_DIR)
    print("=" * 60)


if __name__ == "__main__":
    main()

"""
PPO command-line interface.

Usage:
    python -m ppo init        # create tables
    python -m ppo seed        # seed demo data
    python -m ppo simulate    # run end-to-end scenario
    python -m ppo serve       # start API + dashboard
    python -m ppo status      # print a one-shot status snapshot
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime


def _cmd_init(_args) -> int:
    from ppo.storage.database import init_db

    print("Creating tables...")
    init_db()
    print("Done.")
    return 0


def _cmd_seed(_args) -> int:
    from scripts.seed_db import seed

    seed(reset=True)
    return 0


def _cmd_simulate(_args) -> int:
    from scripts.run_simulation import main as run_sim

    run_sim()
    return 0


def _cmd_serve(_args) -> int:
    from scripts.run_server import main as run_server

    run_server()
    return 0


def _cmd_status(_args) -> int:
    """One-shot system snapshot to stdout."""
    from ppo.data.ais_client import AISClient
    from ppo.data.cruise_schedule import CruiseScheduleClient
    from ppo.data.nordpool_client import NordpoolClient
    from ppo.data.scada_client import SCADAClient
    from ppo.storage.database import SessionLocal, init_db
    from ppo.storage.repositories import (
        BESSStateRepo,
        LeaseRepo,
        TenantRepo,
    )
    from ppo.core.capacity_forecaster import CapacityForecaster

    init_db()
    now = datetime.now()

    ais = AISClient()
    scada = SCADAClient()
    nordpool = NordpoolClient()
    schedule = CruiseScheduleClient()
    forecaster = CapacityForecaster(scada, schedule, ais)

    reading = scada.read(now)
    forecast = forecaster.forecast(horizon_hours=24)

    session = SessionLocal()
    try:
        tenants = TenantRepo(session).all()
        active = LeaseRepo(session).active_at(now)
        bess = BESSStateRepo(session).latest()
    finally:
        session.close()

    spot = nordpool.current()

    print("=" * 60)
    print(f"  PPO Status — {now:%Y-%m-%d %H:%M:%S}")
    print("=" * 60)
    print(f"  Grid capacity:      {reading.grid_capacity_mw:>6.1f} MW")
    print(f"  Cruise load:        {reading.cruise_load_mw:>6.2f} MW")
    print(f"  Tenant load:        {reading.tenant_load_mw:>6.2f} MW")
    print(f"  Idle (now):         {reading.idle_mw:>6.2f} MW")
    print(f"  Utilisation:        {reading.utilisation:>6.1%}")
    print()
    print(f"  Tenants registered: {len(tenants)}")
    print(f"  Active leases:      {len(active)}")
    print()
    print(f"  Spot price:         {spot.price_dkk_kwh:.3f} DKK/kWh")
    print()
    print(f"  Forecast (next 24h):")
    print(f"    Peak leasable:    {forecast.peak_leasable_mw:>6.1f} MW")
    print(f"    Avg leasable:     {forecast.avg_leasable_mw:>6.1f} MW")
    print(f"    Min leasable:     {forecast.min_leasable_mw:>6.1f} MW")
    print(f"    Total leasable:   {forecast.total_leasable_mwh:>6.1f} MWh")
    print()
    if bess:
        print(
            f"  BESS:               "
            f"SoC {bess.state_of_charge:.0%} · {bess.mode.value} · {bess.power_mw:+.2f} MW"
        )
    else:
        print("  BESS:               (no state recorded yet)")
    print("=" * 60)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ppo",
        description="Port Power Orchestrator CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create database tables.").set_defaults(
        func=_cmd_init
    )
    sub.add_parser("seed", help="Seed demo tenants and leases.").set_defaults(
        func=_cmd_seed
    )
    sub.add_parser("simulate", help="Run an end-to-end scenario.").set_defaults(
        func=_cmd_simulate
    )
    sub.add_parser("serve", help="Start the API and dashboard.").set_defaults(
        func=_cmd_serve
    )
    sub.add_parser("status", help="Print a one-shot system snapshot.").set_defaults(
        func=_cmd_status
    )

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""
Seed the database with demo tenants and leases.

Creates a realistic starting state for the dashboard and simulation.
Tenants model Danish licensed energy providers; leases cover overnight
truck charging and BESS operation at Terminal 3.

Usage:
    python -m scripts.seed_db
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ppo.storage.database import SessionLocal, drop_db, init_db
from ppo.storage.models import AssetType, LeaseStatus
from ppo.storage.repositories import (
    AuditLogRepo,
    LeaseRepo,
    TenantRepo,
)


DEMO_TENANTS = [
    {
        "name": "Ørsted Flex",
        "license_number": "DK-EL-TRADER-2019-0147",
        "contact_email": "flex@orsted.dk",
    },
    {
        "name": "CLEVER Charge Partners",
        "license_number": "DK-EL-TRADER-2021-0298",
        "contact_email": "partners@clever.dk",
    },
    {
        "name": "Radius Elnet",
        "license_number": "DK-DSO-0001",
        "contact_email": "b2b@radiuselnet.dk",
    },
]


DEMO_LEASES = [
    # Ørsted Flex: overnight truck charging block + BESS operation
    {
        "tenant": "Ørsted Flex",
        "asset_type": AssetType.TRUCK_CHARGER,
        "asset_identifier": "bay-01",
        "reserved_mw": 1.5,
        "start_offset_hours": -2,
        "duration_hours": 10,
        "price_dkk": 2125.00,
    },
    {
        "tenant": "Ørsted Flex",
        "asset_type": AssetType.TRUCK_CHARGER,
        "asset_identifier": "bay-02",
        "reserved_mw": 1.5,
        "start_offset_hours": -2,
        "duration_hours": 10,
        "price_dkk": 2125.00,
    },
    {
        "tenant": "Ørsted Flex",
        "asset_type": AssetType.BESS,
        "asset_identifier": "bess-t3",
        "reserved_mw": 4.0,
        "start_offset_hours": 0,
        "duration_hours": 24,
        "price_dkk": 14000.00,
    },
    # CLEVER: truck charging block
    {
        "tenant": "CLEVER Charge Partners",
        "asset_type": AssetType.TRUCK_CHARGER,
        "asset_identifier": "bay-03",
        "reserved_mw": 1.5,
        "start_offset_hours": -1,
        "duration_hours": 9,
        "price_dkk": 1913.00,
    },
    {
        "tenant": "CLEVER Charge Partners",
        "asset_type": AssetType.TRUCK_CHARGER,
        "asset_identifier": "bay-04",
        "reserved_mw": 1.5,
        "start_offset_hours": -1,
        "duration_hours": 9,
        "price_dkk": 1913.00,
    },
    # Radius: future block
    {
        "tenant": "Radius Elnet",
        "asset_type": AssetType.TRUCK_CHARGER,
        "asset_identifier": "bay-05",
        "reserved_mw": 1.5,
        "start_offset_hours": 12,
        "duration_hours": 8,
        "price_dkk": 1700.00,
    },
]


def seed(reset: bool = True) -> None:
    if reset:
        print("[seed] Resetting database...")
        drop_db()
    init_db()

    session = SessionLocal()
    tenants = TenantRepo(session)
    leases = LeaseRepo(session)
    audit = AuditLogRepo(session)

    try:
        # ─── Tenants ────────────────────────────────────────────
        tenant_map = {}
        for t_data in DEMO_TENANTS:
            existing = tenants.by_name(t_data["name"])
            if existing:
                tenant_map[t_data["name"]] = existing
                print(f"[seed] Tenant exists: {t_data['name']}")
                continue
            tenant = tenants.create(**t_data)
            tenant_map[t_data["name"]] = tenant
            print(f"[seed] Created tenant: {tenant.name} (id={tenant.id})")

        # ─── Leases ─────────────────────────────────────────────
        now = datetime.now()
        created_leases = 0
        for l_data in DEMO_LEASES:
            tenant = tenant_map[l_data["tenant"]]
            start = now + timedelta(hours=l_data["start_offset_hours"])
            end = start + timedelta(hours=l_data["duration_hours"])

            lease = leases.create(
                tenant_id=tenant.id,
                asset_type=l_data["asset_type"],
                asset_identifier=l_data["asset_identifier"],
                reserved_mw=l_data["reserved_mw"],
                start_time=start,
                end_time=end,
                price_dkk=l_data["price_dkk"],
            )
            # Set status based on time window
            if start <= now <= end:
                lease.status = LeaseStatus.ACTIVE
            elif end < now:
                lease.status = LeaseStatus.COMPLETED
            else:
                lease.status = LeaseStatus.PENDING
            created_leases += 1

        audit.log(
            category="system.seed",
            actor="scripts.seed_db",
            message=(
                f"Seeded {len(DEMO_TENANTS)} tenants and "
                f"{created_leases} leases."
            ),
        )

        session.commit()
        print(
            f"[seed] OK: {len(DEMO_TENANTS)} tenants, "
            f"{created_leases} leases."
        )
    except Exception as exc:
        session.rollback()
        print(f"[seed] FAILED: {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed(reset=True)

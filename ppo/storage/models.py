"""
ORM models.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ppo.storage.database import Base


class LeaseStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CURTAILED = "curtailed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ShedTrigger(str, enum.Enum):
    AIS_ARRIVAL = "ais_arrival"
    DEMAND_SPIKE = "demand_spike"
    SCHEDULED_CRUISE = "scheduled_cruise"
    MANUAL = "manual"
    SAFETY_MARGIN = "safety_margin"


class BESSMode(str, enum.Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    EMERGENCY_DISCHARGE = "emergency_discharge"
    RESERVED = "reserved"


class AssetType(str, enum.Enum):
    TRUCK_CHARGER = "truck_charger"
    BESS = "bess"
    DATA_CENTRE = "data_centre"
    OTHER = "other"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    license_number: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    leases: Mapped[list["Lease"]] = relationship(back_populates="tenant")

    def __repr__(self) -> str:
        return f"<Tenant {self.name}>"


class Lease(Base):
    __tablename__ = "leases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)

    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    asset_identifier: Mapped[str] = mapped_column(String(64), nullable=False)

    reserved_mw: Mapped[float] = mapped_column(Float, nullable=False)

    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    status: Mapped[LeaseStatus] = mapped_column(
        Enum(LeaseStatus), default=LeaseStatus.PENDING, nullable=False
    )

    interruptible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    price_dkk: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="leases")

    def __repr__(self) -> str:
        return (
            f"<Lease id={self.id} tenant={self.tenant_id} "
            f"{self.reserved_mw}MW {self.start_time:%Y-%m-%d %H:%M}>"
        )

    @property
    def duration_hours(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 3600.0


class CapacityForecast(Base):
    __tablename__ = "capacity_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    target_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    predicted_cruise_mw: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_idle_mw: Mapped[float] = mapped_column(Float, nullable=False)
    leasable_mw: Mapped[float] = mapped_column(Float, nullable=False)

    confidence: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<Forecast target={self.target_time:%Y-%m-%d %H:%M} "
            f"idle={self.predicted_idle_mw:.1f}MW>"
        )


class ShedEvent(Base):
    __tablename__ = "shed_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    trigger: Mapped[ShedTrigger] = mapped_column(Enum(ShedTrigger), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    affected_lease_id: Mapped[int | None] = mapped_column(
        ForeignKey("leases.id"), nullable=True
    )

    mw_shed: Mapped[float] = mapped_column(Float, nullable=False)
    response_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ShedEvent trigger={self.trigger.value} "
            f"mw={self.mw_shed:.2f} at={self.triggered_at:%H:%M}>"
        )


class BESSState(Base):
    __tablename__ = "bess_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    state_of_charge: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[BESSMode] = mapped_column(Enum(BESSMode), nullable=False)
    power_mw: Mapped[float] = mapped_column(Float, default=0.0)

    def __repr__(self) -> str:
        return (
            f"<BESSState soc={self.state_of_charge:.0%} "
            f"mode={self.mode.value} power={self.power_mw:+.2f}MW>"
        )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Audit {self.category} {self.timestamp:%Y-%m-%d %H:%M}>"

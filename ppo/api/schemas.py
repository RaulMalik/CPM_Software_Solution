"""Pydantic schemas for API request/response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from ppo.storage.models import AssetType, BESSMode, LeaseStatus, ShedTrigger


# ═══════════════════════════════════════════════════════════════════
# Tenants
# ═══════════════════════════════════════════════════════════════════

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    license_number: str = Field(..., min_length=1, max_length=64)
    contact_email: str


class TenantOut(BaseModel):
    id: int
    name: str
    license_number: str
    contact_email: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════
# Leases
# ═══════════════════════════════════════════════════════════════════

class LeaseCreate(BaseModel):
    tenant_id: int
    asset_type: AssetType
    asset_identifier: str = Field(..., max_length=64)
    requested_mw: float = Field(..., gt=0)
    start_time: datetime
    end_time: datetime


class LeaseOut(BaseModel):
    id: int
    tenant_id: int
    asset_type: AssetType
    asset_identifier: str
    reserved_mw: float
    start_time: datetime
    end_time: datetime
    status: LeaseStatus
    interruptible: bool
    price_dkk: float
    created_at: datetime

    model_config = {"from_attributes": True}


class QuoteOut(BaseModel):
    decision: str
    approved_mw: float
    price_dkk: float
    min_leasable_mw_in_window: float
    reason: str


# ═══════════════════════════════════════════════════════════════════
# Capacity forecast
# ═══════════════════════════════════════════════════════════════════

class ForecastPointOut(BaseModel):
    target_time: datetime
    predicted_cruise_mw: float
    predicted_idle_mw: float
    leasable_mw: float
    confidence: float


class ForecastSummaryOut(BaseModel):
    horizon_hours: int
    generated_at: datetime
    total_leasable_mwh: float
    peak_leasable_mw: float
    min_leasable_mw: float
    avg_leasable_mw: float
    points: list[ForecastPointOut]


# ═══════════════════════════════════════════════════════════════════
# Shed events
# ═══════════════════════════════════════════════════════════════════

class ShedEventOut(BaseModel):
    id: int
    triggered_at: datetime
    trigger: ShedTrigger
    reason: str
    affected_lease_id: Optional[int]
    mw_shed: float
    response_time_seconds: float
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════
# BESS
# ═══════════════════════════════════════════════════════════════════

class BESSStateOut(BaseModel):
    timestamp: datetime
    state_of_charge: float
    mode: BESSMode
    power_mw: float

    model_config = {"from_attributes": True}


class BESSCommandOut(BaseModel):
    target_time: datetime
    action: str
    power_mw: float
    rationale: str


# ═══════════════════════════════════════════════════════════════════
# System status (dashboard summary)
# ═══════════════════════════════════════════════════════════════════

class MeterReadingOut(BaseModel):
    timestamp: datetime
    cruise_load_mw: float
    tenant_load_mw: float
    grid_capacity_mw: float
    idle_mw: float
    utilisation: float


class SystemStatusOut(BaseModel):
    timestamp: datetime
    meter: MeterReadingOut
    active_lease_count: int
    committed_tenant_mw: float
    forecast_summary: ForecastSummaryOut
    latest_bess: Optional[BESSStateOut]
    recent_shed_events: list[ShedEventOut]

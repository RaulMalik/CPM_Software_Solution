"""SCADA client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np

from ppo.config import settings


MONTHLY_CRUISE_GWH = np.array([
    0.02, 0.02, 0.05, 0.20, 1.50, 3.00,
    3.50, 3.00, 1.20, 0.40, 0.05, 0.50
])

HOURLY_SHAPE = np.array([
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    0.30, 0.50, 0.75, 0.85, 0.92, 0.92,
    0.95, 1.00, 0.92, 0.85, 0.75, 0.55,
    0.40, 0.30, 0.20, 0.10, 0.0, 0.0
])


@dataclass(frozen=True)
class MeterReading:
    timestamp: datetime
    cruise_load_mw: float
    tenant_load_mw: float
    grid_capacity_mw: float

    @property
    def total_load_mw(self) -> float:
        return self.cruise_load_mw + self.tenant_load_mw

    @property
    def idle_mw(self) -> float:
        return max(0.0, self.grid_capacity_mw - self.total_load_mw)

    @property
    def utilisation(self) -> float:
        return self.total_load_mw / self.grid_capacity_mw if self.grid_capacity_mw else 0.0


class SCADAClientProtocol(Protocol):
    def read(self, timestamp: datetime | None = None) -> MeterReading:
        ...


class SCADAClient:
    def __init__(
        self,
        grid_capacity_mw: float | None = None,
        tenant_load_fn=None,
    ):
        self.grid_capacity_mw = grid_capacity_mw or settings.grid_capacity_mw
        self._tenant_load_fn = tenant_load_fn or (lambda _ts: 0.0)

    @staticmethod
    def expected_cruise_mw(timestamp: datetime) -> float:
        month_idx = timestamp.month - 1
        hour = timestamp.hour
        monthly_peak = (MONTHLY_CRUISE_GWH[month_idx] / 0.73)
        monthly_peak = min(monthly_peak, settings.grid_capacity_mw)
        return float(monthly_peak * HOURLY_SHAPE[hour])

    def read(self, timestamp: datetime | None = None) -> MeterReading:
        ts = timestamp or datetime.now()
        cruise = self.expected_cruise_mw(ts)
        tenant = max(0.0, self._tenant_load_fn(ts))
        return MeterReading(
            timestamp=ts,
            cruise_load_mw=cruise,
            tenant_load_mw=tenant,
            grid_capacity_mw=self.grid_capacity_mw,
        )

    def history(self, hours: int = 24, step_minutes: int = 15) -> list[MeterReading]:
        now = datetime.now()
        readings: list[MeterReading] = []
        step = timedelta(minutes=step_minutes)
        t = now - timedelta(hours=hours)
        while t <= now:
            readings.append(self.read(t))
            t += step
        return readings

    def set_tenant_load_fn(self, fn) -> None:
        self._tenant_load_fn = fn
"""Cruise schedule client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class CruiseCall:
    vessel_name: str
    mmsi: str
    arrival: datetime
    departure: datetime
    berth: str
    ops_capable: bool
    estimated_load_mw: float

    @property
    def duration_hours(self) -> float:
        return (self.departure - self.arrival).total_seconds() / 3600.0


class CruiseScheduleClient:
    def __init__(self):
        self._bookings: list[CruiseCall] = []

    def add_booking(self, call: CruiseCall) -> None:
        self._bookings.append(call)

    def upcoming(self, window_hours: float = 72.0) -> list[CruiseCall]:
        now = datetime.now()
        cutoff = now + timedelta(hours=window_hours)
        return sorted(
            [c for c in self._bookings if now <= c.arrival <= cutoff],
            key=lambda c: c.arrival,
        )

    def active_now(self) -> list[CruiseCall]:
        now = datetime.now()
        return [c for c in self._bookings if c.arrival <= now <= c.departure]

    def load_at(self, timestamp: datetime) -> float:
        return sum(
            c.estimated_load_mw
            for c in self._bookings
            if c.arrival <= timestamp <= c.departure and c.ops_capable
        )

    def all(self) -> list[CruiseCall]:
        return list(self._bookings)
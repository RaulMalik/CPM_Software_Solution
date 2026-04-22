"""Nordpool client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class SpotPrice:
    timestamp: datetime
    price_dkk_kwh: float


_HOURLY_PRICE_SHAPE = [
    0.55, 0.50, 0.48, 0.48, 0.52, 0.65,
    0.85, 1.15, 1.30, 1.20, 1.05, 0.95,
    0.90, 0.92, 0.95, 1.00, 1.15, 1.35,
    1.40, 1.25, 1.05, 0.85, 0.70, 0.60,
]


class NordpoolClientProtocol(Protocol):
    def prices(self, start: datetime, end: datetime) -> list[SpotPrice]: ...
    def current(self) -> SpotPrice: ...


    def peak_hours(self, threshold: float = 1.1) -> list[int]:
        ...

    def off_peak_hours(self, threshold: float = 0.7) -> list[int]:
        ...


class NordpoolClient:
    def __init__(self, base_price_dkk_kwh: float = 0.65):
        self.base = base_price_dkk_kwh

    def _price_at(self, ts: datetime) -> float:
        multiplier = _HOURLY_PRICE_SHAPE[ts.hour]
        return round(self.base * multiplier, 3)

    def current(self) -> SpotPrice:
        now = datetime.now()
        return SpotPrice(now, self._price_at(now))

    def prices(self, start: datetime, end: datetime) -> list[SpotPrice]:
        prices: list[SpotPrice] = []
        t = start.replace(minute=0, second=0, microsecond=0)
        while t <= end:
            prices.append(SpotPrice(t, self._price_at(t)))
            t += timedelta(hours=1)
        return prices

    def peak_hours(self, threshold: float = 1.1) -> list[int]:
        return [h for h, m in enumerate(_HOURLY_PRICE_SHAPE) if m >= threshold]

    def off_peak_hours(self, threshold: float = 0.7) -> list[int]:
        return [h for h, m in enumerate(_HOURLY_PRICE_SHAPE) if m <= threshold]
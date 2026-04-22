"""AIS client."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, Sequence


@dataclass(frozen=True)
class VesselArrival:
    mmsi: str
    name: str
    eta: datetime
    distance_nm: float
    ops_capable: bool
    estimated_load_mw: float
    berth: str


class AISClientProtocol(Protocol):
    def upcoming_arrivals(self, within_hours: float = 24.0) -> Sequence[VesselArrival]:
        ...


class AISClient:
    _FLEET = [
        ("AIDAnova", 12.0, True),
        ("AIDAperla", 11.5, True),
        ("MSC Preziosa", 9.5, True),
        ("Costa Diadema", 8.0, False),
        ("Norwegian Star", 7.5, False),
        ("Seabourn Ovation", 4.5, True),
    ]

    _BERTHS = ["Oceankaj-T1", "Oceankaj-T2", "Oceankaj-T3",
               "Langelinie-N", "Langelinie-S"]

    def __init__(self, seed: int | None = None, now: datetime | None = None):
        self._rng = random.Random(seed)
        self._now_override = now
        self._scheduled: list[VesselArrival] = []

    def _now(self) -> datetime:
        return self._now_override or datetime.now()

    def schedule(self, arrival: VesselArrival) -> None:
        self._scheduled.append(arrival)

    def upcoming_arrivals(self, within_hours: float = 24.0) -> Sequence[VesselArrival]:
        cutoff = self._now() + timedelta(hours=within_hours)
        arrivals = [a for a in self._scheduled if a.eta <= cutoff]

        if not self._scheduled:
            for _ in range(self._rng.randint(0, 2)):
                name, load, ops = self._rng.choice(self._FLEET)
                eta_hours = self._rng.uniform(1, within_hours)
                distance = eta_hours * 15
                arrivals.append(
                    VesselArrival(
                        mmsi=f"211{self._rng.randint(100000, 999999)}",
                        name=name,
                        eta=self._now() + timedelta(hours=eta_hours),
                        distance_nm=distance,
                        ops_capable=ops,
                        estimated_load_mw=load,
                        berth=self._rng.choice(self._BERTHS),
                    )
                )
        return arrivals

    def imminent_arrivals(
        self, within_hours: float = 2.0
    ) -> Sequence[VesselArrival]:
        return [
            a
            for a in self.upcoming_arrivals(within_hours)
            if a.ops_capable
        ]
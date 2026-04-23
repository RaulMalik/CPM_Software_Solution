"""BESS Controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from ppo.config import settings
from ppo.data.ais_client import AISClient
from ppo.data.nordpool_client import NordpoolClient
from ppo.storage.models import BESSMode
from ppo.storage.repositories import AuditLogRepo, BESSStateRepo


class CommandAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    HOLD = "hold"
    EMERGENCY_DISCHARGE = "emergency_discharge"
    RESERVE = "reserve"


@dataclass
class BESSCommand:
    target_time: datetime
    action: CommandAction
    power_mw: float
    rationale: str


@dataclass
class BESSPlan:
    generated_at: datetime
    current_soc: float
    commands: list[BESSCommand] = field(default_factory=list)

    @property
    def next_action(self) -> BESSCommand | None:
        return self.commands[0] if self.commands else None


class BESSController:
    def __init__(
        self,
        ais: AISClient,
        nordpool: NordpoolClient,
        bess_state_repo: BESSStateRepo,
        audit_repo: AuditLogRepo | None = None,
    ):
        self.ais = ais
        self.nordpool = nordpool
        self.state_repo = bess_state_repo
        self.audit_repo = audit_repo

    def current_soc(self) -> float:
        latest = self.state_repo.latest()
        return latest.state_of_charge if latest else 0.5

    def plan(
        self,
        horizon_hours: int = 24,
        start: datetime | None = None,
    ) -> BESSPlan:
        start = (start or datetime.now()).replace(
            minute=0, second=0, microsecond=0
        )
        soc = self.current_soc()

        peak_hours = set(self.nordpool.peak_hours())
        off_peak_hours = set(self.nordpool.off_peak_hours())

        commands: list[BESSCommand] = []
        for h in range(horizon_hours):
            target = start + timedelta(hours=h)

            cmd = self._decide(target, soc, peak_hours, off_peak_hours)
            commands.append(cmd)

            soc = self._apply_command_to_soc(soc, cmd)

        return BESSPlan(
            generated_at=datetime.now(),
            current_soc=self.current_soc(),
            commands=commands,
        )

    def execute_next(self, plan: BESSPlan) -> BESSCommand | None:
        cmd = plan.next_action
        if not cmd:
            return None

        mode_map = {
            CommandAction.CHARGE: BESSMode.CHARGING,
            CommandAction.DISCHARGE: BESSMode.DISCHARGING,
            CommandAction.EMERGENCY_DISCHARGE: BESSMode.EMERGENCY_DISCHARGE,
            CommandAction.RESERVE: BESSMode.RESERVED,
            CommandAction.HOLD: BESSMode.IDLE,
        }
        mode = mode_map.get(cmd.action, BESSMode.IDLE)

        new_soc = self._apply_command_to_soc(plan.current_soc, cmd)

        self.state_repo.record(
            state_of_charge=round(new_soc, 4),
            mode=mode,
            power_mw=cmd.power_mw,
        )

        if self.audit_repo:
            self.audit_repo.log(
                category="bess.action",
                actor="ppo.bess_controller",
                message=f"BESS {cmd.action.value}: {cmd.rationale}",
                metadata={
                    "power_mw": cmd.power_mw,
                    "soc_after": round(new_soc, 4),
                },
            )
        return cmd

    def _decide(
        self,
        target: datetime,
        soc: float,
        peak_hours: set[int],
        off_peak_hours: set[int],
    ) -> BESSCommand:
        imminent = self.ais.imminent_arrivals(
            within_hours=settings.cruise_ais_detection_hours
        )
        if imminent and soc > settings.bess_min_soc:
            return BESSCommand(
                target_time=target,
                action=CommandAction.EMERGENCY_DISCHARGE,
                power_mw=settings.bess_power_mw,
                rationale=(
                    f"Cruise ship imminent ({imminent[0].name} ETA "
                    f"{imminent[0].eta:%H:%M}); discharging to support grid."
                ),
            )

        if imminent:
            return BESSCommand(
                target_time=target,
                action=CommandAction.RESERVE,
                power_mw=0.0,
                rationale=(
                    "Holding SoC for incoming cruise call; pausing charge cycle."
                ),
            )

        hour = target.hour
        if (
            hour in off_peak_hours
            and soc < settings.bess_max_soc
        ):
            rate = self._charge_rate(soc)
            return BESSCommand(
                target_time=target,
                action=CommandAction.CHARGE,
                power_mw=-rate,
                rationale=f"Off-peak hour {hour:02d}:00; charging at {rate:.2f} MW.",
            )

        if (
            hour in peak_hours
            and soc > settings.bess_min_soc
        ):
            rate = self._discharge_rate(soc)
            return BESSCommand(
                target_time=target,
                action=CommandAction.DISCHARGE,
                power_mw=rate,
                rationale=f"Peak hour {hour:02d}:00; discharging at {rate:.2f} MW.",
            )

        return BESSCommand(
            target_time=target,
            action=CommandAction.HOLD,
            power_mw=0.0,
            rationale=f"Hour {hour:02d}:00; holding.",
        )

    def _charge_rate(self, soc: float) -> float:
        max_rate = settings.bess_power_mw
        if soc > 0.85:
            return max_rate * 0.5
        return max_rate

    def _discharge_rate(self, soc: float) -> float:
        max_rate = settings.bess_power_mw
        if soc < 0.25:
            return max_rate * 0.5
        return max_rate

    def _apply_command_to_soc(self, soc: float, cmd: BESSCommand) -> float:
        capacity = settings.bess_capacity_mwh
        eta = settings.bess_round_trip_efficiency ** 0.5
        if cmd.action in (CommandAction.CHARGE,):
            energy_in = -cmd.power_mw * 1.0 * eta
            return min(settings.bess_max_soc, soc + energy_in / capacity)
        if cmd.action in (
            CommandAction.DISCHARGE,
            CommandAction.EMERGENCY_DISCHARGE,
        ):
            energy_out = cmd.power_mw * 1.0 / eta
            return max(settings.bess_min_soc, soc - energy_out / capacity)
        return soc
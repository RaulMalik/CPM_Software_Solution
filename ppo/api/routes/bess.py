"""BESS state and planning routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ppo.api.deps import get_bess_controller, get_bess_state_repo
from ppo.api.schemas import BESSCommandOut, BESSStateOut
from ppo.core.bess_controller import BESSController
from ppo.storage.repositories import BESSStateRepo

router = APIRouter(prefix="/bess", tags=["bess"])


@router.get("/state", response_model=BESSStateOut)
def current_state(repo: BESSStateRepo = Depends(get_bess_state_repo)):
    latest = repo.latest()
    if not latest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No BESS state recorded yet.",
        )
    return latest


@router.get("/history", response_model=list[BESSStateOut])
def history(
    hours: int = Query(24, ge=1, le=720),
    repo: BESSStateRepo = Depends(get_bess_state_repo),
):
    return repo.history(hours=hours)


@router.get("/plan", response_model=list[BESSCommandOut])
def plan(
    horizon_hours: int = Query(24, ge=1, le=168),
    controller: BESSController = Depends(get_bess_controller),
):
    """Forward-looking charge/discharge plan."""
    bess_plan = controller.plan(horizon_hours=horizon_hours)
    return [
        BESSCommandOut(
            target_time=c.target_time,
            action=c.action.value,
            power_mw=c.power_mw,
            rationale=c.rationale,
        )
        for c in bess_plan.commands
    ]

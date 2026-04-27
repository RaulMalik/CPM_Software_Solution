"""Shed event audit trail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ppo.api.deps import get_shed_event_repo
from ppo.api.schemas import ShedEventOut
from ppo.storage.repositories import ShedEventRepo

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/shed", response_model=list[ShedEventOut])
def list_shed_events(
    hours: int = Query(24, ge=1, le=720),
    repo: ShedEventRepo = Depends(get_shed_event_repo),
):
    """Recent load-shedding actions (audit trail)."""
    return repo.recent(hours=hours)

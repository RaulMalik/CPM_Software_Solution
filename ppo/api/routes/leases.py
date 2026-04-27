"""Lease booking and management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ppo.api.deps import get_lease_manager, get_lease_repo
from ppo.api.schemas import LeaseCreate, LeaseOut, QuoteOut
from ppo.core.lease_manager import LeaseManager, LeaseRequest, QuoteDecision
from ppo.storage.repositories import LeaseRepo

router = APIRouter(prefix="/leases", tags=["leases"])


def _as_request(body: LeaseCreate) -> LeaseRequest:
    return LeaseRequest(
        tenant_id=body.tenant_id,
        asset_type=body.asset_type,
        asset_identifier=body.asset_identifier,
        requested_mw=body.requested_mw,
        start_time=body.start_time,
        end_time=body.end_time,
    )


@router.get("", response_model=list[LeaseOut])
def list_leases(repo: LeaseRepo = Depends(get_lease_repo)):
    return repo.all()


@router.post("/quote", response_model=QuoteOut)
def quote_lease(
    body: LeaseCreate,
    manager: LeaseManager = Depends(get_lease_manager),
):
    """Evaluate whether the request can be accommodated and at what price."""
    quote = manager.quote(_as_request(body))
    return QuoteOut(
        decision=quote.decision.value,
        approved_mw=quote.approved_mw,
        price_dkk=quote.price_dkk,
        min_leasable_mw_in_window=quote.min_leasable_mw_in_window,
        reason=quote.reason,
    )


@router.post("", response_model=LeaseOut, status_code=status.HTTP_201_CREATED)
def create_lease(
    body: LeaseCreate,
    manager: LeaseManager = Depends(get_lease_manager),
):
    lease, quote = manager.book(_as_request(body))
    if lease is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=quote.reason or "Lease could not be booked.",
        )
    return lease


@router.get("/{lease_id}", response_model=LeaseOut)
def get_lease(lease_id: int, repo: LeaseRepo = Depends(get_lease_repo)):
    lease = repo.get(lease_id)
    if not lease:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found."
        )
    return lease


@router.delete("/{lease_id}", response_model=LeaseOut)
def cancel_lease(
    lease_id: int,
    manager: LeaseManager = Depends(get_lease_manager),
):
    lease = manager.cancel(lease_id, reason="Cancelled via API.")
    if not lease:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found."
        )
    return lease

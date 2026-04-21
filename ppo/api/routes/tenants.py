"""Tenant CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ppo.api.deps import get_tenant_repo
from ppo.api.schemas import TenantCreate, TenantOut
from ppo.storage.repositories import TenantRepo

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut])
def list_tenants(repo: TenantRepo = Depends(get_tenant_repo)):
    return repo.all()


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(body: TenantCreate, repo: TenantRepo = Depends(get_tenant_repo)):
    if repo.by_name(body.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant '{body.name}' already exists.",
        )
    return repo.create(
        name=body.name,
        license_number=body.license_number,
        contact_email=body.contact_email,
    )


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: int, repo: TenantRepo = Depends(get_tenant_repo)):
    tenant = repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found."
        )
    return tenant

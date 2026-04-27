"""Server-rendered HTML dashboard for CMP operators."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ppo.api.deps import (
    get_bess_state_repo,
    get_forecaster,
    get_lease_repo,
    get_scada,
    get_shed_event_repo,
    get_tenant_repo,
)
from ppo.config import settings
from ppo.core.capacity_forecaster import CapacityForecaster
from ppo.data.scada_client import SCADAClient
from ppo.storage.repositories import (
    BESSStateRepo,
    LeaseRepo,
    ShedEventRepo,
    TenantRepo,
)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
def root(request: Request):
    """Redirect root to the dashboard."""
    return templates.TemplateResponse(
        request, "landing.html", {"request": request, "title": "Port Power Orchestrator"}
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    scada: SCADAClient = Depends(get_scada),
    lease_repo: LeaseRepo = Depends(get_lease_repo),
    tenant_repo: TenantRepo = Depends(get_tenant_repo),
    bess_repo: BESSStateRepo = Depends(get_bess_state_repo),
    shed_repo: ShedEventRepo = Depends(get_shed_event_repo),
    forecaster: CapacityForecaster = Depends(get_forecaster),
):
    now = datetime.now()
    reading = scada.read(now)
    summary = forecaster.forecast(horizon_hours=24)
    active = lease_repo.active_at(now)
    tenants = tenant_repo.all()
    latest_bess = bess_repo.latest()
    shed_events = shed_repo.recent(hours=24)

    ctx = {
        "request": request,
        "now": now,
        "reading": reading,
        "forecast": summary,
        "active_leases": active,
        "committed_mw": sum(l.reserved_mw for l in active),
        "tenants": tenants,
        "latest_bess": latest_bess,
        "shed_events": shed_events,
        "settings": settings,
    }
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/dashboard/tenants", response_class=HTMLResponse)
def tenants_page(
    request: Request,
    tenant_repo: TenantRepo = Depends(get_tenant_repo),
    lease_repo: LeaseRepo = Depends(get_lease_repo),
):
    tenants = tenant_repo.all()
    ctx = {
        "request": request,
        "tenants": tenants,
        "leases_by_tenant": {
            t.id: lease_repo.by_tenant(t.id) for t in tenants
        },
    }
    return templates.TemplateResponse(request, "tenants.html", ctx)

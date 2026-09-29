from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.m2m.auth import require_m2m_capability
from app.m2m.context import M2MContext
from app.m2m.schemas import M2MResponseEnvelope
from app.m2m.scopes import M2M_API_VERSION, M2M_CONTRACT_VERSION
from app.m2m.service import M2MReadService


router = APIRouter(prefix="/api/v1/m2m", tags=["m2m"])
_service = M2MReadService()


def _envelope(
    *,
    context: M2MContext,
    data: Any,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "ok": True,
        "request_id": context.request_id,
        "execution_id": context.execution_id,
        "correlation_id": context.correlation_id,
        "tenant_id": context.tenant_id,
        "capability": context.requested_capability,
        "status": "completed",
        "data": data,
        "error": None,
        "meta": {
            "api_version": M2M_API_VERSION,
            "contract_version": M2M_CONTRACT_VERSION,
            "service_version": settings.release_version,
            "release_sha": settings.release_sha,
        },
    }


@router.get("/health", response_model=M2MResponseEnvelope)
def health(
    request: Request,
    context: M2MContext = Depends(require_m2m_capability("fintech.health.read")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return _envelope(
        context=context,
        data=_service.health(db, settings),
        settings=settings,
    )


@router.get("/runtime", response_model=M2MResponseEnvelope)
def runtime(
    request: Request,
    context: M2MContext = Depends(require_m2m_capability("fintech.runtime.read")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return _envelope(
        context=context,
        data=_service.runtime(db, settings),
        settings=settings,
    )


@router.get("/capabilities", response_model=M2MResponseEnvelope)
def capabilities(
    request: Request,
    context: M2MContext = Depends(require_m2m_capability("fintech.capabilities.read")),
    settings: Settings = Depends(get_settings),
):
    return _envelope(
        context=context,
        data=_service.capabilities(),
        settings=settings,
    )


@router.get("/audit/events", response_model=M2MResponseEnvelope)
def audit_events(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    from_ts: datetime | None = Query(None),
    to_ts: datetime | None = Query(None),
    context: M2MContext = Depends(require_m2m_capability("fintech.audit.read")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    events, next_cursor = _service.audit_events(
        db,
        tenant_id=context.tenant_id,
        limit=limit,
        cursor=cursor,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    data = {
        "items": [
            {
                "audit_event_id": event.audit_event_id,
                "actor_id": event.actor_id,
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "request_id": event.request_id,
                "correlation_id": event.correlation_id,
                "occurred_at": event.occurred_at,
            }
            for event in events
        ],
        "next_cursor": next_cursor,
    }
    return _envelope(context=context, data=data, settings=settings)

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditEvent
from app.persistent_consent_ledger import PersistentConsentLedger


logger = logging.getLogger("fintech.m2m.audit")
_persistent_ledger = PersistentConsentLedger()


def _safe_uuid(value: str | None) -> str | None:
    try:
        return str(UUID(str(value or "")))
    except ValueError:
        return None


def record_m2m_audit(
    db: Session,
    *,
    context,
    decision: str,
    status_code: int,
    latency_ms: float,
    error_code: str | None,
) -> AuditEvent:
    detail = {
        "service_id": context.service_subject,
        "client_id": context.client_id,
        "credential_id": context.credential_id,
        "environment": context.source_environment,
        "organization_id": context.organization_id,
        "service_principal_id": context.service_principal_id,
        "execution_id": context.execution_id,
        "capability": context.requested_capability,
        "scope": context.requested_capability,
        "decision": decision,
        "status": status_code,
        "latency_ms": latency_ms,
        "error_code": error_code,
        "governance_mode": context.governance_mode,
        "write_allowed": context.write_allowed,
        "execution_allowed": context.execution_allowed,
        "data_classification": context.data_classification,
    }
    event = AuditEvent(
        tenant_id=context.tenant_id,
        actor_id=context.service_principal_id,
        action="M2M_REQUEST",
        resource_type="M2M_CAPABILITY",
        resource_id=context.requested_capability,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        detail=detail,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    _persistent_ledger.append_audit_event(
        db,
        tenant_id=event.tenant_id,
        actor_id=event.actor_id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        request_id=event.request_id,
        correlation_id=event.correlation_id,
        detail=event.detail,
        occurred_at=event.occurred_at,
    )
    return event


async def m2m_audit_middleware(request: Request, call_next):
    if not request.url.path.startswith("/api/v1/m2m/"):
        return await call_next(request)

    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        latency_ms = round((perf_counter() - started) * 1000, 3)
        request.state.m2m_error_code = "M2M_INTERNAL_ERROR"
        logger.exception(
            "M2M_UNHANDLED_EXCEPTION",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "execution_id": getattr(request.state, "m2m_execution_id", None),
                "correlation_id": getattr(request.state, "correlation_id", None),
                "event_code": "M2M_UNHANDLED_EXCEPTION",
            },
        )
        context = getattr(request.state, "m2m_context", None)
        response = JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "request_id": getattr(request.state, "request_id", None),
                "execution_id": getattr(request.state, "m2m_execution_id", None),
                "correlation_id": getattr(request.state, "correlation_id", None),
                "tenant_id": getattr(context, "tenant_id", None),
                "capability": getattr(request.state, "m2m_requested_capability", None),
                "status": "failed",
                "data": None,
                "error": {
                    "code": "M2M_INTERNAL_ERROR",
                    "message": "Falha interna no processamento M2M.",
                    "details": [],
                },
                "meta": {
                    "api_version": "v1",
                    "contract_version": "m2m-r1",
                },
            },
        )
    latency_ms = round((perf_counter() - started) * 1000, 3)
    context = getattr(request.state, "m2m_context", None)
    error_code = getattr(request.state, "m2m_error_code", None)
    decision = "allow" if response.status_code < 400 else "deny"

    log_payload = {
        "event_code": "M2M_REQUEST_DECISION",
        "service_id": getattr(context, "service_subject", None),
        "client_id": getattr(context, "client_id", None),
        "credential_id": getattr(context, "credential_id", None),
        "tenant_id": getattr(context, "tenant_id", None),
        "organization_id": getattr(context, "organization_id", None),
        "request_id": getattr(request.state, "request_id", None),
        "execution_id": getattr(request.state, "m2m_execution_id", None),
        "correlation_id": getattr(request.state, "correlation_id", None),
        "capability": getattr(request.state, "m2m_requested_capability", None),
        "decision": decision,
        "status": response.status_code,
        "latency_ms": latency_ms,
        "error_code": error_code,
    }
    logger.info("M2M_REQUEST_DECISION", extra=log_payload)

    # Only a fully validated tenant/service context is persisted. Requests that
    # fail before tenant validation remain observable in structured logs but
    # cannot write into an untrusted tenant's audit chain.
    if context is not None:
        try:
            with SessionLocal() as db:
                record_m2m_audit(
                    db,
                    context=context,
                    decision=decision,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    error_code=error_code,
                )
                db.commit()
        except Exception:
            logger.exception(
                "M2M_AUDIT_PERSISTENCE_FAILED",
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "execution_id": getattr(request.state, "m2m_execution_id", None),
                    "correlation_id": getattr(request.state, "correlation_id", None),
                    "event_code": "M2M_AUDIT_PERSISTENCE_FAILED",
                },
            )
            return JSONResponse(
                status_code=500,
                content={
                    "ok": False,
                    "request_id": getattr(request.state, "request_id", None),
                    "execution_id": getattr(request.state, "m2m_execution_id", None),
                    "correlation_id": getattr(request.state, "correlation_id", None),
                    "tenant_id": context.tenant_id,
                    "capability": context.requested_capability,
                    "status": "failed",
                    "data": None,
                    "error": {
                        "code": "M2M_INTERNAL_ERROR",
                        "message": "Falha ao persistir auditoria obrigatória.",
                        "details": [],
                    },
                    "meta": {
                        "api_version": "v1",
                        "contract_version": "m2m-r1",
                    },
                },
            )

    response.headers["X-Execution-ID"] = (
        getattr(request.state, "m2m_execution_id", None) or ""
    )
    return response

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.contracts.post_closing import ConsentLedgerIntegrityRead
from app.db import get_db
from app.errors import ApiError
from app.models import ConsentGrantRecord
from app.persistent_consent_ledger import PersistentConsentLedger, PersistentConsentViolation
from app.security import SecurityContext, require_security_context


router = APIRouter(prefix="/api/v1/consent", tags=["consent-ledger"])
ledger = PersistentConsentLedger()
INTERNAL_ROLES = {"ANALYST", "PLATFORM_ADMIN", "INTERNAL_AGENT", "CREDIT_ANALYST"}


class ConsentGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_ref: str = Field(min_length=1, max_length=128, description="Identificador pseudonimizado do titular")
    purpose: str = Field(min_length=3, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=50)
    recipient: str = Field(min_length=2, max_length=255)
    source_institution: str = Field(min_length=2, max_length=255)
    expires_at: datetime
    granted_at: datetime | None = None
    provider_reference: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConsentGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    consent_id: str
    tenant_id: str
    subject_ref: str
    purpose: str
    scopes: list[str]
    recipient: str
    source_institution: str
    provider_reference: str | None
    granted_at: datetime
    expires_at: datetime
    status: str
    revoked_at: datetime | None
    created_by: str
    created_at: datetime


class ConsentGrantRevoke(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ConsentAccessRequest(BaseModel):
    purpose: str = Field(min_length=3, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=50)
    provider_reference: str | None = Field(default=None, max_length=255)


def _grant_read(row: ConsentGrantRecord) -> ConsentGrantRead:
    return ConsentGrantRead(
        consent_id=row.consent_id,
        tenant_id=row.tenant_id,
        subject_ref=row.subject_ref,
        purpose=row.purpose,
        scopes=list(row.scopes or []),
        recipient=row.recipient,
        source_institution=row.source_institution,
        provider_reference=row.provider_reference,
        granted_at=row.granted_at,
        expires_at=row.expires_at,
        status=row.status,
        revoked_at=row.revoked_at,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _audit(request: Request, context: SecurityContext, db: Session, action: str, resource_id: str, detail: dict[str, Any] | None = None) -> None:
    record_audit(
        db,
        context=context,
        action=action,
        resource_type="CONSENT_LEDGER",
        resource_id=resource_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
        detail=detail or {},
    )


@router.post("/grants", response_model=ConsentGrantRead, status_code=status.HTTP_201_CREATED)
def issue_grant(
    payload: ConsentGrantCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ConsentGrantRead:
    now = datetime.now(timezone.utc)
    try:
        row = ledger.issue_grant(
            db,
            tenant_id=context.tenant_id,
            subject_ref=payload.subject_ref,
            purpose=payload.purpose,
            scopes=payload.scopes,
            recipient=payload.recipient,
            source_institution=payload.source_institution,
            granted_at=payload.granted_at or now,
            expires_at=payload.expires_at,
            created_by=context.user_id,
            provider_reference=payload.provider_reference,
            metadata=payload.metadata,
            request_id=request.state.request_id,
            correlation_id=request.state.correlation_id,
        )
    except ValueError as exc:
        db.rollback()
        raise ApiError(422, "CONSENT_GRANT_INVALID", str(exc)) from exc
    _audit(request, context, db, "CONSENT_GRANTED", row.consent_id, {"purpose": row.purpose, "scopes": row.scopes})
    db.commit()
    db.refresh(row)
    return _grant_read(row)


@router.post("/grants/{consent_id}/revoke", response_model=ConsentGrantRead)
def revoke_grant(
    consent_id: str,
    payload: ConsentGrantRevoke,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ConsentGrantRead:
    try:
        row = ledger.revoke_grant(
            db,
            consent_id=consent_id,
            actor_id=context.user_id,
            request_id=request.state.request_id,
            correlation_id=request.state.correlation_id,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise ApiError(404, "CONSENT_NOT_FOUND", "Consentimento não encontrado.") from exc
    _audit(request, context, db, "CONSENT_REVOKED", consent_id, {"reason": payload.reason})
    db.commit()
    db.refresh(row)
    return _grant_read(row)


@router.post("/grants/{consent_id}/access", response_model=ConsentGrantRead)
def authorize_access(
    consent_id: str,
    payload: ConsentAccessRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ConsentGrantRead:
    try:
        row = ledger.authorize_access(
            db,
            consent_id=consent_id,
            actor_id=context.user_id,
            purpose=payload.purpose,
            scopes=payload.scopes,
            provider_reference=payload.provider_reference,
            request_id=request.state.request_id,
            correlation_id=request.state.correlation_id,
        )
    except KeyError as exc:
        raise ApiError(404, "CONSENT_NOT_FOUND", "Consentimento não encontrado.") from exc
    except PersistentConsentViolation as exc:
        raise ApiError(403, "CONSENT_ACCESS_DENIED", str(exc)) from exc
    _audit(request, context, db, "CONSENT_ACCESS_ALLOWED", consent_id, {"purpose": payload.purpose, "scopes": payload.scopes})
    db.commit()
    db.refresh(row)
    return _grant_read(row)


@router.get("/integrity/{tenant_id}", response_model=ConsentLedgerIntegrityRead)
def verify_integrity(
    tenant_id: str,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ConsentLedgerIntegrityRead:
    if context.role not in INTERNAL_ROLES:
        raise ApiError(403, "INTERNAL_ONLY", "A verificação de integridade é uma operação interna.")
    return ConsentLedgerIntegrityRead(**ledger.verify_chain(db, tenant_id=tenant_id))

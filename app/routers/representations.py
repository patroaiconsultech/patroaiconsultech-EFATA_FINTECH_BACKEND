from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.errors import ApiError
from app.models import Lead, RepresentationAuthorization, ResourceGrant
from app.representation_state import require_representation_transition
from app.schemas import RepresentationCreate, RepresentationRead
from app.security import SecurityContext, require_client_authorizer, require_security_context

router = APIRouter(prefix="/api/v1/representations", tags=["representations"])


@router.post("", response_model=RepresentationRead, status_code=201)
def create_representation(
    payload: RepresentationCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> RepresentationAuthorization:
    lead = db.scalar(
        select(Lead).where(Lead.lead_id == payload.lead_id, Lead.tenant_id == context.tenant_id)
    )
    if lead is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Recurso não encontrado.")

    representation = RepresentationAuthorization(
        originator_tenant_id=context.tenant_id,
        represented_tenant_id=payload.represented_tenant_id,
        lead_id=payload.lead_id,
        allowed_actions=payload.allowed_actions,
        created_by=context.user_id,
    )
    db.add(representation)
    db.flush()
    record_audit(
        db,
        context=context,
        action="REPRESENTATION_REQUESTED",
        resource_type="REPRESENTATION",
        resource_id=representation.authorization_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
    )
    db.commit()
    db.refresh(representation)
    return representation


@router.post("/{authorization_id}/accept", response_model=RepresentationRead)
def accept_representation(
    authorization_id: str,
    request: Request,
    context: SecurityContext = Depends(require_client_authorizer),
    db: Session = Depends(get_db),
) -> RepresentationAuthorization:
    representation = db.scalar(
        select(RepresentationAuthorization).where(
            RepresentationAuthorization.authorization_id == authorization_id
        )
    )
    if representation is None or representation.represented_tenant_id != context.tenant_id:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Recurso não encontrado.")
    require_representation_transition(
        representation.status,
        "ACTIVE",
    )

    representation.status = "ACTIVE"
    representation.accepted_by = context.user_id
    representation.accepted_at = datetime.now(timezone.utc)
    record_audit(
        db,
        context=context,
        action="REPRESENTATION_ACCEPTED",
        resource_type="REPRESENTATION",
        resource_id=representation.authorization_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
    )
    db.commit()
    db.refresh(representation)
    return representation


@router.post("/{authorization_id}/revoke", response_model=RepresentationRead)
def revoke_representation(
    authorization_id: str,
    request: Request,
    context: SecurityContext = Depends(require_client_authorizer),
    db: Session = Depends(get_db),
) -> RepresentationAuthorization:
    representation = db.scalar(
        select(RepresentationAuthorization).where(
            RepresentationAuthorization.authorization_id == authorization_id
        )
    )
    if representation is None or representation.represented_tenant_id != context.tenant_id:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Recurso não encontrado.")

    require_representation_transition(
        representation.status,
        "REVOKED",
    )

    revoked_at = datetime.now(timezone.utc)
    representation.status = "REVOKED"
    representation.revoked_at = revoked_at

    db.execute(
        update(ResourceGrant)
        .where(
            ResourceGrant.source_type == "REPRESENTATION_AUTHORIZATION",
            ResourceGrant.source_id == representation.authorization_id,
            ResourceGrant.status == "ACTIVE",
        )
        .values(status="REVOKED", revoked_at=revoked_at)
    )

    record_audit(
        db,
        context=context,
        action="REPRESENTATION_REVOKED",
        resource_type="REPRESENTATION",
        resource_id=representation.authorization_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
    )
    db.commit()
    db.refresh(representation)
    return representation

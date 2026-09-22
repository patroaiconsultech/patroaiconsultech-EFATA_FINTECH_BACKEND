from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.errors import ApiError
from app.models import Lead
from app.schemas import LeadCreate, LeadRead
from app.security import SecurityContext, require_security_context

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])


@router.post("", response_model=LeadRead, status_code=201)
def create_lead(
    payload: LeadCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> Lead:
    lead = Lead(
        tenant_id=context.tenant_id,
        prospective_client_name=payload.prospective_client_name,
        opportunity_type=payload.opportunity_type,
        estimated_amount=payload.estimated_amount,
        currency=payload.currency.upper(),
        created_by=context.user_id,
    )
    db.add(lead)
    db.flush()
    record_audit(
        db,
        context=context,
        action="LEAD_CREATED",
        resource_type="LEAD",
        resource_id=lead.lead_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
    )
    db.commit()
    db.refresh(lead)
    return lead


@router.get("", response_model=list[LeadRead])
def list_leads(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[Lead]:
    return list(
        db.scalars(
            select(Lead).where(Lead.tenant_id == context.tenant_id).order_by(Lead.created_at.desc())
        ).all()
    )


@router.get("/{lead_id}", response_model=LeadRead)
def get_lead(
    lead_id: str,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> Lead:
    lead = db.scalar(
        select(Lead).where(Lead.lead_id == lead_id, Lead.tenant_id == context.tenant_id)
    )
    if lead is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Recurso não encontrado.")
    return lead

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.access import get_accessible_opportunity, get_granted_resource_ids
from app.audit import record_audit
from app.authorization import derive_representation_grant_permissions, require_representation_action
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import (
    CapitalOpportunity,
    Lead,
    RepresentationAuthorization,
    ResourceGrant,
)
from app.schemas import OpportunityCreate, OpportunityRead
from app.security import SecurityContext, require_security_context

router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunities"])


@router.post("", response_model=OpportunityRead, status_code=201)
def create_opportunity(
    payload: OpportunityCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CapitalOpportunity:
    representation = db.scalar(
        select(RepresentationAuthorization).where(
            RepresentationAuthorization.authorization_id == payload.representation_authorization_id,
            RepresentationAuthorization.originator_tenant_id == context.tenant_id,
            RepresentationAuthorization.status == "ACTIVE",
        )
    )
    if representation is None:
        raise ApiError(403, "REPRESENTATION_NOT_AUTHORIZED", "Representação não autorizada.")
    require_representation_action(representation.allowed_actions, "CREATE_OPPORTUNITY")

    lead = db.scalar(select(Lead).where(Lead.lead_id == representation.lead_id))
    if lead is None:
        raise ApiError(409, "SOURCE_LEAD_MISSING", "Lead de origem indisponível.")

    opportunity = CapitalOpportunity(
        tenant_id=representation.represented_tenant_id,
        source_lead_id=lead.lead_id,
        representation_authorization_id=representation.authorization_id,
        title=payload.title,
        opportunity_type=lead.opportunity_type,
        requested_amount=lead.estimated_amount,
        currency=lead.currency,
        purpose=payload.purpose,
        created_by=context.user_id,
    )
    db.add(opportunity)
    db.flush()

    originator_permissions = derive_representation_grant_permissions(
        representation.allowed_actions
    )
    if originator_permissions:
        db.add(
            ResourceGrant(
                owner_tenant_id=opportunity.tenant_id,
                grantee_tenant_id=context.tenant_id,
                resource_type="OPPORTUNITY",
                resource_id=opportunity.opportunity_id,
                permissions=originator_permissions,
                source_type="REPRESENTATION_AUTHORIZATION",
                source_id=representation.authorization_id,
                created_by=context.user_id,
            )
        )

    platform_tenant_id = get_settings().platform_tenant_id
    if platform_tenant_id and platform_tenant_id not in {opportunity.tenant_id, context.tenant_id}:
        db.add(
            ResourceGrant(
                owner_tenant_id=opportunity.tenant_id,
                grantee_tenant_id=platform_tenant_id,
                resource_type="OPPORTUNITY",
                resource_id=opportunity.opportunity_id,
                permissions=["READ", "QUALIFY"],
                source_type="PLATFORM_ASSIGNMENT",
                source_id=opportunity.opportunity_id,
                created_by=context.user_id,
            )
        )

    record_audit(
        db,
        context=context,
        action="OPPORTUNITY_CREATED",
        resource_type="OPPORTUNITY",
        resource_id=opportunity.opportunity_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
        tenant_id=opportunity.tenant_id,
    )
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[CapitalOpportunity]:
    granted_ids = get_granted_resource_ids(
        db,
        tenant_id=context.tenant_id,
        resource_type="OPPORTUNITY",
        required_permission="READ",
    )
    return list(
        db.scalars(
            select(CapitalOpportunity)
            .where(
                or_(
                    CapitalOpportunity.tenant_id == context.tenant_id,
                    CapitalOpportunity.opportunity_id.in_(granted_ids),
                )
            )
            .order_by(CapitalOpportunity.created_at.desc())
        ).all()
    )


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(
    opportunity_id: str,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CapitalOpportunity:
    return get_accessible_opportunity(
        db,
        opportunity_id=opportunity_id,
        tenant_id=context.tenant_id,
        required_permission="READ",
    )

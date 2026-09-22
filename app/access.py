from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import CapitalOpportunity, ResourceGrant


def get_granted_resource_ids(
    db: Session,
    *,
    tenant_id: str,
    resource_type: str,
    required_permission: str,
) -> list[str]:
    grants = db.scalars(
        select(ResourceGrant).where(
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.grantee_tenant_id == tenant_id,
            ResourceGrant.status == "ACTIVE",
        )
    ).all()
    return [
        grant.resource_id
        for grant in grants
        if required_permission in grant.permissions
    ]


def get_accessible_opportunity(
    db: Session,
    *,
    opportunity_id: str,
    tenant_id: str,
    required_permission: str = "READ",
) -> CapitalOpportunity:
    opportunity = db.scalar(
        select(CapitalOpportunity).where(
            CapitalOpportunity.opportunity_id == opportunity_id
        )
    )
    if opportunity is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Recurso não encontrado.")

    if opportunity.tenant_id == tenant_id:
        return opportunity

    granted_ids = get_granted_resource_ids(
        db,
        tenant_id=tenant_id,
        resource_type="OPPORTUNITY",
        required_permission=required_permission,
    )
    if opportunity_id in granted_ids:
        return opportunity

    # Non-enumeration: inaccessible resources look absent.
    raise ApiError(404, "RESOURCE_NOT_FOUND", "Recurso não encontrado.")

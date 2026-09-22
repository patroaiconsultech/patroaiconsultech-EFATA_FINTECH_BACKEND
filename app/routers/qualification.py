from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.access import get_accessible_opportunity
from app.audit import record_audit
from app.db import get_db
from app.errors import ApiError
from app.models import QualificationCase
from app.optimistic_lock import update_opportunity_stage_if_version
from app.schemas import QualificationCreate, QualificationRead
from app.security import SecurityContext, require_analyst

router = APIRouter(prefix="/api/v1/opportunities", tags=["qualification"])


def qualification_stage(result: str) -> str:
    if result in {"ELIGIBLE", "CONDITIONALLY_ELIGIBLE"}:
        return "QUALIFIED"
    if result == "NOT_ELIGIBLE":
        return "REJECTED"
    return "INFORMATION_PENDING"


@router.post(
    "/{opportunity_id}/qualification",
    response_model=QualificationRead,
    status_code=201,
)
def qualify_opportunity(
    opportunity_id: str,
    payload: QualificationCreate,
    request: Request,
    if_match: str = Header(..., alias="If-Match"),
    context: SecurityContext = Depends(require_analyst),
    db: Session = Depends(get_db),
) -> QualificationCase:
    opportunity = get_accessible_opportunity(
        db,
        opportunity_id=opportunity_id,
        tenant_id=context.tenant_id,
        required_permission="QUALIFY",
    )
    try:
        expected_version = int(if_match.strip('"'))
    except ValueError as exc:
        raise ApiError(
            400,
            "INVALID_IF_MATCH",
            "Versão esperada inválida.",
        ) from exc

    new_stage = qualification_stage(payload.result)
    updated = update_opportunity_stage_if_version(
        db,
        opportunity_id=opportunity.opportunity_id,
        expected_version=expected_version,
        new_stage=new_stage,
    )
    if not updated:
        db.rollback()
        raise ApiError(
            409,
            "VERSION_CONFLICT",
            "O recurso foi alterado por outra operação.",
        )

    qualification = QualificationCase(
        tenant_id=opportunity.tenant_id,
        opportunity_id=opportunity.opportunity_id,
        result=payload.result,
        conclusion=payload.conclusion,
        created_by=context.user_id,
    )
    db.add(qualification)

    record_audit(
        db,
        context=context,
        action="OPPORTUNITY_QUALIFIED",
        resource_type="OPPORTUNITY",
        resource_id=opportunity.opportunity_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
        tenant_id=opportunity.tenant_id,
        detail={
            "result": payload.result,
            "stage": new_stage,
            "previous_version": expected_version,
            "new_version": expected_version + 1,
        },
    )
    db.commit()
    db.refresh(qualification)
    return qualification

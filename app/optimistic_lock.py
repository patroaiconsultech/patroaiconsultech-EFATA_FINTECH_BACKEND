from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import CapitalOpportunity
from app.models import utcnow


def update_opportunity_stage_if_version(
    db: Session,
    *,
    opportunity_id: str,
    expected_version: int,
    new_stage: str,
) -> bool:
    result = db.execute(
        update(CapitalOpportunity)
        .where(
            CapitalOpportunity.opportunity_id == opportunity_id,
            CapitalOpportunity.version == expected_version,
        )
        .values(
            stage=new_stage,
            version=expected_version + 1,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1

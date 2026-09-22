from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import CapitalOpportunity
from app.optimistic_lock import update_opportunity_stage_if_version
from tests.test_authorization_lifecycle import create_active_opportunity


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Real concurrent update proof requires PostgreSQL.",
)
def test_only_one_concurrent_update_wins_on_postgresql(
    client,
    ids,
    auth_headers,
):
    _, opportunity_id = create_active_opportunity(
        client,
        ids,
        auth_headers,
        ["CREATE_OPPORTUNITY", "VIEW_STATUS"],
    )
    barrier = Barrier(2)

    def attempt(new_stage: str) -> bool:
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            updated = update_opportunity_stage_if_version(
                db,
                opportunity_id=opportunity_id,
                expected_version=1,
                new_stage=new_stage,
            )
            if updated:
                db.commit()
            else:
                db.rollback()
            return updated

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                attempt,
                ["QUALIFIED", "INFORMATION_PENDING"],
            )
        )

    assert sorted(results) == [False, True]

    with SessionLocal() as db:
        opportunity = db.scalar(
            select(CapitalOpportunity).where(
                CapitalOpportunity.opportunity_id == opportunity_id
            )
        )
        assert opportunity is not None
        assert opportunity.version == 2
        assert opportunity.stage in {
            "QUALIFIED",
            "INFORMATION_PENDING",
        }

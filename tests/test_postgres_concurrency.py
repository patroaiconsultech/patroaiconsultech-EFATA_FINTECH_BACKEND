import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ReconciliationInboxRecord, ReconciliationReviewRecord, User


pytestmark = pytest.mark.postgres

if os.getenv("RUN_POSTGRES_INTEGRATION") != "1" or not os.getenv("FINTECH_DATABASE_URL", "").startswith("postgresql"):
    pytest.skip("requires RUN_POSTGRES_INTEGRATION=1 and a PostgreSQL DATABASE_URL", allow_module_level=True)


WORKER_A_ID = "30000000-0000-0000-0000-000000000001"
WORKER_B_ID = "30000000-0000-0000-0000-000000000002"


def seed_open_review() -> str:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        # assigned_to is an FK to iam_users.user_id. Use real IAM principals
        # so this test exercises row-lock concurrency rather than failing on
        # an invalid assignee fixture.
        db.add_all(
            [
                User(
                    user_id=WORKER_A_ID,
                    email="pg-worker-a@tests.efata.invalid",
                    display_name="PostgreSQL Worker A",
                    status="ACTIVE",
                    created_at=now,
                ),
                User(
                    user_id=WORKER_B_ID,
                    email="pg-worker-b@tests.efata.invalid",
                    display_name="PostgreSQL Worker B",
                    status="ACTIVE",
                    created_at=now,
                ),
            ]
        )
        db.flush()

        inbox = ReconciliationInboxRecord(
            source="POSTGRES_CONCURRENCY_TEST",
            external_event_id="event-concurrency-1",
            payload={"fixture": True},
            status="REVIEW_REQUIRED",
            received_at=now,
        )
        db.add(inbox)
        db.flush()
        review = ReconciliationReviewRecord(
            inbox_id=inbox.inbox_id,
            status="OPEN",
            reason="AMOUNT_VARIANCE",
            expected_amount="100.00",
            received_amount="101.00",
            amount_variance="1.00",
            currency="BRL",
            due_at=now,
            created_at=now,
        )
        db.add(review)
        db.commit()
        return review.review_id


def claim_one(barrier: Barrier, worker_id: str) -> list[str]:
    barrier.wait(timeout=10)
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(ReconciliationReviewRecord)
                .where(ReconciliationReviewRecord.status == "OPEN")
                .order_by(ReconciliationReviewRecord.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            ).all()
        )
        for row in rows:
            row.status = "CLAIMED"
            row.assigned_to = worker_id
        db.commit()
        return [row.review_id for row in rows]


def test_two_postgres_workers_claim_one_review_once():
    review_id = seed_open_review()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(claim_one, barrier, WORKER_A_ID),
            executor.submit(claim_one, barrier, WORKER_B_ID),
        ]
        claimed = [review for future in futures for review in future.result()]

    assert claimed.count(review_id) == 1
    with SessionLocal() as db:
        row = db.get(ReconciliationReviewRecord, review_id)
        assert row.status == "CLAIMED"
        assert row.assigned_to in {WORKER_A_ID, WORKER_B_ID}

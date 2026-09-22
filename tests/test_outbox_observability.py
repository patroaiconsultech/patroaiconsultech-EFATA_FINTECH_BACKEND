from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import ReconciliationOutboxRecord
from app.outbox_observability import OutboxObservabilityService
from app.persistent_reconciliation import MAX_OUTBOX_ATTEMPTS, PersistentReconciliationService


def test_outbox_claim_records_lease_and_reclaims_expired_event():
    service = PersistentReconciliationService()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = ReconciliationOutboxRecord(
            event_key="test:event:lease",
            event_type="TEST",
            aggregate_type="TEST",
            aggregate_id="aggregate-1",
            payload={"ok": True},
            status="PENDING",
            available_at=now,
            created_at=now - timedelta(minutes=10),
        )
        db.add(row)
        db.commit()

        claimed = service.claim_outbox(db, limit=1, lease_seconds=1)
        assert len(claimed) == 1
        assert claimed[0].status == "PROCESSING"
        assert claimed[0].attempt_count == 1
        assert claimed[0].claimed_at is not None
        assert claimed[0].lease_until is not None
        db.commit()

        claimed[0].lease_until = now - timedelta(seconds=1)
        db.commit()
        reclaimed = service.claim_outbox(db, limit=1, lease_seconds=60)
        assert len(reclaimed) == 1
        assert reclaimed[0].attempt_count == 2
        db.rollback()


def test_outbox_failure_moves_to_dead_letter_after_max_attempts():
    service = PersistentReconciliationService()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = ReconciliationOutboxRecord(
            event_key="test:event:dead-letter",
            event_type="TEST",
            aggregate_type="TEST",
            aggregate_id="aggregate-2",
            payload={"ok": False},
            status="PROCESSING",
            attempt_count=MAX_OUTBOX_ATTEMPTS,
            available_at=now,
            created_at=now,
        )
        db.add(row)
        db.commit()
        updated = service.mark_outbox(db, outbox_id=row.outbox_id, published=False, error="provider down")
        assert updated.status == "DEAD_LETTER"
        assert updated.dead_lettered_at is not None
        assert updated.failed_at is not None


def test_outbox_metrics_raise_alert_for_old_pending_event():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(
            ReconciliationOutboxRecord(
                event_key="test:event:metrics",
                event_type="TEST",
                aggregate_type="TEST",
                aggregate_id="aggregate-3",
                payload={"ok": True},
                status="PENDING",
                available_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=20),
            )
        )
        db.commit()
        metrics = OutboxObservabilityService().snapshot(db, now=now, pending_sla_seconds=300)
        assert metrics["pending_count"] == 1
        assert metrics["oldest_pending_age_seconds"] >= 1200
        assert "OUTBOX_PENDING_LAG_OVER_SLA" in metrics["alerts"]

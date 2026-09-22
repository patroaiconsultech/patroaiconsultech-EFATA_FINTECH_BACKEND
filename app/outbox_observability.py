"""Operational metrics and SLA alerts for the reconciliation outbox."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ReconciliationOutboxRecord


class OutboxObservabilityService:
    """Keep monitoring read-only, aggregate-based and safe for operators."""

    def snapshot(
        self,
        db: Session,
        *,
        now: datetime | None = None,
        pending_sla_seconds: int = 300,
        processing_sla_seconds: int = 120,
        max_attempts: int = 8,
    ) -> dict[str, object]:
        captured_at = now or datetime.now(timezone.utc)
        counts = dict(
            db.execute(
                select(ReconciliationOutboxRecord.status, func.count(ReconciliationOutboxRecord.outbox_id))
                .group_by(ReconciliationOutboxRecord.status)
            ).all()
        )
        pending_created_at = db.scalar(
            select(func.min(ReconciliationOutboxRecord.created_at)).where(
                ReconciliationOutboxRecord.status == "PENDING"
            )
        )
        processing_started_at = db.scalar(
            select(func.min(func.coalesce(ReconciliationOutboxRecord.claimed_at, ReconciliationOutboxRecord.created_at))).where(
                ReconciliationOutboxRecord.status == "PROCESSING"
            )
        )
        retry_total = db.scalar(select(func.coalesce(func.sum(ReconciliationOutboxRecord.attempt_count), 0))) or 0
        overdue_processing_count = db.scalar(
            select(func.count(ReconciliationOutboxRecord.outbox_id)).where(
                ReconciliationOutboxRecord.status == "PROCESSING",
                ReconciliationOutboxRecord.lease_until.is_not(None),
                ReconciliationOutboxRecord.lease_until < captured_at,
            )
        ) or 0
        published_last_24h = db.scalar(
            select(func.count(ReconciliationOutboxRecord.outbox_id)).where(
                ReconciliationOutboxRecord.status == "PUBLISHED",
                ReconciliationOutboxRecord.published_at >= captured_at - timedelta(hours=24),
            )
        ) or 0
        failed_last_24h = db.scalar(
            select(func.count(ReconciliationOutboxRecord.outbox_id)).where(
                ReconciliationOutboxRecord.failed_at >= captured_at - timedelta(hours=24),
            )
        ) or 0

        pending_age = self._age_seconds(pending_created_at, captured_at)
        processing_age = self._age_seconds(processing_started_at, captured_at)
        dead_letter_count = int(counts.get("DEAD_LETTER", 0))
        alerts: list[str] = []
        if pending_age > pending_sla_seconds:
            alerts.append("OUTBOX_PENDING_LAG_OVER_SLA")
        if processing_age > processing_sla_seconds or overdue_processing_count:
            alerts.append("OUTBOX_PROCESSING_LEASE_OVERDUE")
        if dead_letter_count:
            alerts.append("OUTBOX_DEAD_LETTER_NOT_EMPTY")
        if int(retry_total) > max_attempts:
            alerts.append("OUTBOX_RETRY_VOLUME_HIGH")

        return {
            "captured_at": captured_at,
            "pending_count": int(counts.get("PENDING", 0)),
            "processing_count": int(counts.get("PROCESSING", 0)),
            "published_count": int(counts.get("PUBLISHED", 0)),
            "dead_letter_count": dead_letter_count,
            "retry_total": int(retry_total),
            "oldest_pending_age_seconds": pending_age,
            "oldest_processing_age_seconds": processing_age,
            "overdue_processing_count": int(overdue_processing_count),
            "published_last_24h": int(published_last_24h),
            "failed_last_24h": int(failed_last_24h),
            "alerts": alerts,
        }

    @staticmethod
    def _age_seconds(value: datetime | None, now: datetime) -> float:
        if value is None:
            return 0.0
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0.0, round((now - value).total_seconds(), 3))

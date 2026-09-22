"""PostgreSQL-backed reconciliation service for flow J.

The service keeps the same deterministic policy as the in-memory prototype,
but moves the state boundary to SQLAlchemy models. PostgreSQL is the target
runtime: inbox uniqueness prevents duplicate processing, row locks serialize
competing workers, and an outbox event is committed with the ledger mutation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CommissionLedgerEntryRecord,
    ReconciliationInboxRecord,
    ReconciliationLinkRecord,
    ReconciliationOutboxRecord,
    ReconciliationReviewRecord,
)
from app.post_closing import CommissionLedgerEntry, CommissionStatus, InvalidTransition
from app.reconciliation_engine import (
    CommissionReconciliationEngine,
    ReconciliationDecision,
    ReconciliationReason,
    ReconciliationResult,
    SettlementEvent,
)


POLICY_VERSION = "commission-reconciliation-v1"
REVIEW_SLA_HOURS = 24
OUTBOX_LEASE_SECONDS = 120
MAX_OUTBOX_ATTEMPTS = 8


class PersistentReconciliationService:
    """Durable flow-J state machine; caller owns the SQL transaction."""

    def __init__(self, *, amount_tolerance: Decimal = Decimal("0.01")) -> None:
        self.amount_tolerance = amount_tolerance

    def register_commission(
        self,
        db: Session,
        *,
        match_id: str,
        beneficiary_tenant_id: str,
        trigger_event: str,
        base_amount: Decimal,
        rate_bps: int,
        currency: str = "BRL",
        contract_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CommissionLedgerEntryRecord:
        entry = CommissionLedgerEntry.estimate(
            match_id=match_id,
            beneficiary_tenant_id=beneficiary_tenant_id,
            trigger_event=trigger_event,
            base_amount=base_amount,
            rate_bps=rate_bps,
            currency=currency.upper(),
            contract_id=contract_id,
        )
        row = CommissionLedgerEntryRecord(
            commission_id=entry.commission_id,
            match_id=entry.match_id,
            beneficiary_tenant_id=entry.beneficiary_tenant_id,
            contract_id=entry.contract_id,
            trigger_event=entry.trigger_event,
            base_amount=entry.base_amount,
            rate_bps=entry.rate_bps,
            estimated_amount=entry.estimated_amount,
            status=entry.status.value,
            currency=entry.currency,
            metadata_json={**(metadata or {}), "policy_version": POLICY_VERSION},
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
        db.add(row)
        db.flush()
        return row

    def transition_commission(
        self,
        db: Session,
        *,
        commission_id: str,
        status: CommissionStatus,
        contract_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CommissionLedgerEntryRecord:
        row = db.scalar(
            select(CommissionLedgerEntryRecord)
            .where(CommissionLedgerEntryRecord.commission_id == commission_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(commission_id)
        updated = self._to_domain(row).transition(status, contract_id=contract_id, metadata=metadata)
        self._copy_domain(row, updated)
        db.flush()
        return row

    def reconcile(self, db: Session, event: SettlementEvent) -> ReconciliationResult:
        """Process one event within the caller's transaction.

        The inbox insert is protected by a unique constraint on source/event.
        A duplicate returns a duplicate result without mutating the ledger.
        Candidate rows are locked before any status transition.
        """
        inbox = self._insert_inbox(db, event)
        if inbox is None:
            return ReconciliationResult(
                reconciliation_id=f"reconciliation-{uuid4()}",
                external_event_id=event.external_event_id,
                decision=ReconciliationDecision.DUPLICATE,
                reason=ReconciliationReason.DUPLICATE_EXTERNAL_EVENT,
                commission_id=None,
                candidate_commission_ids=(),
                amount_variance=None,
                policy_version=POLICY_VERSION,
                reconciled_at=datetime.now(timezone.utc),
                detail={"source": event.source},
            )

        now = datetime.now(timezone.utc)
        inbox.status = "PROCESSING"
        inbox.processing_started_at = now
        inbox.attempt_count += 1
        db.flush()

        rows = list(
            db.scalars(
                select(CommissionLedgerEntryRecord)
                .where(
                    CommissionLedgerEntryRecord.beneficiary_tenant_id == event.beneficiary_tenant_id,
                    CommissionLedgerEntryRecord.currency == event.currency.upper(),
                    CommissionLedgerEntryRecord.status.not_in({"VOIDED", "RECONCILED"}),
                )
                .with_for_update()
            ).all()
        )
        result, selected, expected_amount = self._decide(event, rows)
        link = ReconciliationLinkRecord(
            inbox_id=inbox.inbox_id,
            commission_id=selected.commission_id if selected else None,
            decision=result.decision.value,
            reason=result.reason.value,
            amount_variance=result.amount_variance,
            detail=result.detail,
        )
        db.add(link)
        db.flush()

        if result.decision is ReconciliationDecision.REVIEW_REQUIRED:
            db.add(
                ReconciliationReviewRecord(
                    inbox_id=inbox.inbox_id,
                    link_id=link.link_id,
                    status="OPEN",
                    reason=result.reason.value,
                    expected_amount=expected_amount,
                    received_amount=event.amount,
                    amount_variance=result.amount_variance,
                    currency=event.currency.upper(),
                    due_at=now + timedelta(hours=REVIEW_SLA_HOURS),
                )
            )

        if result.decision is ReconciliationDecision.AUTO_RECONCILED and selected is not None:
            domain_entry = self._to_domain(selected)
            updated = domain_entry
            if updated.status is CommissionStatus.ELIGIBLE:
                updated = updated.transition(CommissionStatus.INVOICED, metadata={"reconciliation_id": result.reconciliation_id})
            if updated.status is CommissionStatus.INVOICED:
                updated = updated.transition(CommissionStatus.RECEIVED, metadata={"reconciliation_id": result.reconciliation_id})
            if updated.status is CommissionStatus.RECEIVED:
                updated = updated.transition(CommissionStatus.RECONCILED, metadata={"reconciliation_id": result.reconciliation_id})
            self._copy_domain(selected, updated)
            db.add(
                ReconciliationOutboxRecord(
                    event_key=f"commission-reconciled:{event.external_event_id}:{selected.commission_id}",
                    event_type="COMMISSION_RECONCILED",
                    aggregate_type="COMMISSION_LEDGER",
                    aggregate_id=selected.commission_id,
                    payload={
                        "commission_id": selected.commission_id,
                        "external_event_id": event.external_event_id,
                        "source": event.source,
                        "amount": str(event.amount),
                        "currency": event.currency.upper(),
                        "policy_version": POLICY_VERSION,
                    },
                    status="PENDING",
                    available_at=now,
                    created_at=now,
                )
            )

        inbox.status = "PROCESSED" if result.decision is not ReconciliationDecision.REVIEW_REQUIRED else "REVIEW_REQUIRED"
        inbox.processed_at = now
        db.flush()
        return result

    def claim_reviews(self, db: Session, *, limit: int = 50, actor_id: str | None = None) -> list[ReconciliationReviewRecord]:
        """Claim open reviews using PostgreSQL `FOR UPDATE SKIP LOCKED`."""
        rows = list(
            db.scalars(
                select(ReconciliationReviewRecord)
                .where(ReconciliationReviewRecord.status == "OPEN")
                .order_by(ReconciliationReviewRecord.due_at.asc(), ReconciliationReviewRecord.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            ).all()
        )
        for row in rows:
            row.status = "CLAIMED"
            row.assigned_to = actor_id
        db.flush()
        return rows

    def resolve_review(
        self,
        db: Session,
        *,
        review_id: str,
        actor_id: str,
        decision: str,
        notes: str,
    ) -> ReconciliationReviewRecord:
        row = db.scalar(
            select(ReconciliationReviewRecord)
            .where(ReconciliationReviewRecord.review_id == review_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(review_id)
        if row.status not in {"OPEN", "CLAIMED"}:
            raise ValueError(f"review {review_id} is already {row.status}")
        if row.assigned_to and row.assigned_to != actor_id:
            raise PermissionError("review is assigned to another operator")
        if decision not in {"ACCEPT_VARIANCE", "REJECT_VARIANCE", "REQUEST_INFORMATION"}:
            raise ValueError("unsupported review decision")

        now = datetime.now(timezone.utc)
        inbox = db.scalar(
            select(ReconciliationInboxRecord)
            .where(ReconciliationInboxRecord.inbox_id == row.inbox_id)
            .with_for_update()
        )
        link = db.scalar(
            select(ReconciliationLinkRecord)
            .where(ReconciliationLinkRecord.link_id == row.link_id)
            .with_for_update()
        ) if row.link_id else None
        commission = None
        if link and link.commission_id:
            commission = db.scalar(
                select(CommissionLedgerEntryRecord)
                .where(CommissionLedgerEntryRecord.commission_id == link.commission_id)
                .with_for_update()
            )

        if decision == "ACCEPT_VARIANCE":
            if commission is None:
                raise ValueError("a variance acceptance requires a linked commission")
            self._advance_to_reconciled(commission, review_id=review_id)
            row.status = "RESOLVED"
            if inbox:
                inbox.status = "PROCESSED"
            if link:
                link.decision = "MANUAL_ACCEPTED"
                link.reason = "HUMAN_ACCEPTED_VARIANCE"
                link.detail = {**(link.detail or {}), "review_id": review_id, "notes": notes}
            db.add(
                ReconciliationOutboxRecord(
                    event_key=f"commission-manually-reconciled:{review_id}",
                    event_type="COMMISSION_MANUALLY_RECONCILED",
                    aggregate_type="COMMISSION_LEDGER",
                    aggregate_id=commission.commission_id,
                    payload={"commission_id": commission.commission_id, "review_id": review_id, "decision": decision, "notes": notes},
                    status="PENDING",
                    available_at=now,
                    created_at=now,
                )
            )
        elif decision == "REJECT_VARIANCE":
            if commission is not None and commission.status not in {"VOIDED", "DISPUTED"}:
                commission.status = "DISPUTED"
                commission.metadata_json = {**(commission.metadata_json or {}), "review_id": review_id, "dispute_notes": notes}
                commission.updated_at = now
            row.status = "RESOLVED"
            if inbox:
                inbox.status = "DISPUTED"
            if link:
                link.decision = "MANUAL_REJECTED"
                link.reason = "HUMAN_REJECTED_VARIANCE"
                link.detail = {**(link.detail or {}), "review_id": review_id, "notes": notes}
            db.add(
                ReconciliationOutboxRecord(
                    event_key=f"commission-disputed:{review_id}",
                    event_type="COMMISSION_RECONCILIATION_DISPUTED",
                    aggregate_type="RECONCILIATION_REVIEW",
                    aggregate_id=review_id,
                    payload={"review_id": review_id, "commission_id": commission.commission_id if commission else None, "decision": decision, "notes": notes},
                    status="PENDING",
                    available_at=now,
                    created_at=now,
                )
            )
        else:
            row.status = "WAITING_INFORMATION"
            row.decision = decision
            row.notes = notes
            row.resolved_at = None
            if inbox:
                inbox.status = "REVIEW_REQUIRED"
            db.add(
                ReconciliationOutboxRecord(
                    event_key=f"commission-information-requested:{review_id}:{now.isoformat()}",
                    event_type="COMMISSION_RECONCILIATION_INFORMATION_REQUESTED",
                    aggregate_type="RECONCILIATION_REVIEW",
                    aggregate_id=review_id,
                    payload={"review_id": review_id, "commission_id": commission.commission_id if commission else None, "decision": decision, "notes": notes},
                    status="PENDING",
                    available_at=now,
                    created_at=now,
                )
            )

        row.assigned_to = actor_id
        row.decision = decision
        row.notes = notes
        if row.status == "RESOLVED":
            row.resolved_at = now
        db.flush()
        return row

    def claim_outbox(
        self,
        db: Session,
        *,
        limit: int = 100,
        lease_seconds: int = OUTBOX_LEASE_SECONDS,
    ) -> list[ReconciliationOutboxRecord]:
        """Claim pending or lease-expired events with `FOR UPDATE SKIP LOCKED`."""
        now = datetime.now(timezone.utc)
        rows = list(
            db.scalars(
                select(ReconciliationOutboxRecord)
                .where(
                    or_(
                        and_(
                            ReconciliationOutboxRecord.status == "PENDING",
                            ReconciliationOutboxRecord.available_at <= now,
                        ),
                        and_(
                            ReconciliationOutboxRecord.status == "PROCESSING",
                            ReconciliationOutboxRecord.lease_until.is_not(None),
                            ReconciliationOutboxRecord.lease_until < now,
                        ),
                    )
                )
                .order_by(ReconciliationOutboxRecord.available_at.asc(), ReconciliationOutboxRecord.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            ).all()
        )
        for row in rows:
            row.status = "PROCESSING"
            row.attempt_count += 1
            row.claimed_at = now
            row.lease_until = now + timedelta(seconds=lease_seconds)
            row.last_attempt_at = now
        db.flush()
        return rows

    def mark_outbox(
        self,
        db: Session,
        *,
        outbox_id: str,
        published: bool,
        error: str | None = None,
        retry_after_seconds: int = 60,
    ) -> ReconciliationOutboxRecord:
        row = db.scalar(
            select(ReconciliationOutboxRecord)
            .where(ReconciliationOutboxRecord.outbox_id == outbox_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(outbox_id)
        now = datetime.now(timezone.utc)
        if published:
            row.status = "PUBLISHED"
            row.published_at = now
            row.claimed_at = None
            row.lease_until = None
            row.failed_at = None
            row.last_error = None
        else:
            row.failed_at = now
            row.last_error = error or "publisher_failed"
            row.claimed_at = None
            row.lease_until = None
            if row.attempt_count >= MAX_OUTBOX_ATTEMPTS:
                row.status = "DEAD_LETTER"
                row.dead_lettered_at = now
                row.available_at = now
            else:
                row.status = "PENDING"
                row.available_at = now + timedelta(seconds=retry_after_seconds)
        db.flush()
        return row

    def _advance_to_reconciled(self, row: CommissionLedgerEntryRecord, *, review_id: str) -> None:
        updated = self._to_domain(row)
        metadata = {"review_id": review_id, "reconciliation_policy": POLICY_VERSION}
        if updated.status is CommissionStatus.ELIGIBLE:
            updated = updated.transition(CommissionStatus.INVOICED, metadata=metadata)
        if updated.status is CommissionStatus.INVOICED:
            updated = updated.transition(CommissionStatus.RECEIVED, metadata=metadata)
        if updated.status is CommissionStatus.RECEIVED:
            updated = updated.transition(CommissionStatus.RECONCILED, metadata=metadata)
        if updated.status is not CommissionStatus.RECONCILED:
            raise InvalidTransition(f"commission {updated.commission_id} cannot be manually reconciled from {updated.status}")
        self._copy_domain(row, updated)

    def _insert_inbox(self, db: Session, event: SettlementEvent) -> ReconciliationInboxRecord | None:
        payload = {
            "external_event_id": event.external_event_id,
            "beneficiary_tenant_id": event.beneficiary_tenant_id,
            "amount": str(event.amount),
            "currency": event.currency.upper(),
            "settled_at": event.settled_at.isoformat(),
            "contract_id": event.contract_id,
            "match_id": event.match_id,
            "invoice_reference": event.invoice_reference,
            "account_fingerprint": event.account_fingerprint,
            "source": event.source,
            "metadata": event.metadata or {},
        }
        try:
            with db.begin_nested():
                inbox = ReconciliationInboxRecord(
                    source=event.source,
                    external_event_id=event.external_event_id,
                    payload=payload,
                    status="RECEIVED",
                    received_at=datetime.now(timezone.utc),
                )
                db.add(inbox)
                db.flush()
                return inbox
        except IntegrityError:
            return None

    def _decide(
        self,
        event: SettlementEvent,
        rows: list[CommissionLedgerEntryRecord],
    ) -> tuple[ReconciliationResult, CommissionLedgerEntryRecord | None, Decimal | None]:
        candidates: list[tuple[CommissionLedgerEntryRecord, bool, bool, bool, Decimal]] = []
        for row in rows:
            metadata = row.metadata_json or {}
            reference_match = bool(event.invoice_reference and metadata.get("invoice_reference") == event.invoice_reference)
            contract_match = bool(event.contract_id and row.contract_id == event.contract_id)
            match_match = bool(event.match_id and row.match_id == event.match_id)
            if not (reference_match or contract_match or match_match):
                continue
            variance = abs(Decimal(str(row.estimated_amount)) - event.amount)
            candidates.append((row, reference_match, contract_match, match_match, variance))

        now = datetime.now(timezone.utc)
        if not candidates:
            return self._result(event, ReconciliationDecision.UNMATCHED, ReconciliationReason.NO_CANDIDATE, None, (), None, {"source": event.source}), None, None

        candidates.sort(key=lambda item: (int(item[1]), int(item[2]), int(item[3]), int(item[4] == 0)), reverse=True)
        best = candidates[0]
        ordered_ids = tuple(item[0].commission_id for item in candidates)
        if len(candidates) > 1 and self._rank(best) == self._rank(candidates[1]):
            result = self._result(event, ReconciliationDecision.REVIEW_REQUIRED, ReconciliationReason.AMBIGUOUS_CANDIDATES, None, ordered_ids, best[4], {"source": event.source, "candidate_count": str(len(candidates))})
            return result, None, Decimal(str(best[0].estimated_amount))

        row, reference_match, contract_match, match_match, variance = best
        if variance > self.amount_tolerance:
            result = self._result(event, ReconciliationDecision.REVIEW_REQUIRED, ReconciliationReason.AMOUNT_VARIANCE, row.commission_id, ordered_ids, variance, {"source": event.source, "expected": str(row.estimated_amount), "received": str(event.amount)})
            return result, row, Decimal(str(row.estimated_amount))

        if not ((reference_match and contract_match) or (contract_match and match_match)) or row.status not in {"ELIGIBLE", "INVOICED", "RECEIVED"}:
            result = self._result(event, ReconciliationDecision.REVIEW_REQUIRED, ReconciliationReason.COMMISSION_NOT_READY, row.commission_id, ordered_ids, variance, {"source": event.source, "current_status": row.status})
            return result, row, Decimal(str(row.estimated_amount))

        result = self._result(event, ReconciliationDecision.AUTO_RECONCILED, ReconciliationReason.EXACT_REFERENCE_AND_AMOUNT, row.commission_id, ordered_ids, variance, {"source": event.source, "currency": event.currency.upper()})
        return result, row, Decimal(str(row.estimated_amount))

    def _result(
        self,
        event: SettlementEvent,
        decision: ReconciliationDecision,
        reason: ReconciliationReason,
        commission_id: str | None,
        candidates: tuple[str, ...],
        variance: Decimal | None,
        detail: dict[str, str],
    ) -> ReconciliationResult:
        return ReconciliationResult(
            reconciliation_id=f"reconciliation-{uuid4()}",
            external_event_id=event.external_event_id,
            decision=decision,
            reason=reason,
            commission_id=commission_id,
            candidate_commission_ids=candidates,
            amount_variance=variance,
            policy_version=POLICY_VERSION,
            reconciled_at=datetime.now(timezone.utc),
            detail=detail,
        )

    @staticmethod
    def _rank(item: tuple[CommissionLedgerEntryRecord, bool, bool, bool, Decimal]) -> tuple[int, int, int, int]:
        return (int(item[1]), int(item[2]), int(item[3]), int(item[4] == 0))

    @staticmethod
    def _to_domain(row: CommissionLedgerEntryRecord) -> CommissionLedgerEntry:
        return CommissionLedgerEntry(
            commission_id=row.commission_id,
            match_id=row.match_id,
            beneficiary_tenant_id=row.beneficiary_tenant_id,
            contract_id=row.contract_id,
            trigger_event=row.trigger_event,
            base_amount=Decimal(str(row.base_amount)),
            rate_bps=row.rate_bps,
            estimated_amount=Decimal(str(row.estimated_amount)),
            status=CommissionStatus(row.status),
            currency=row.currency,
            created_at=row.created_at,
            updated_at=row.updated_at,
            metadata={str(key): str(value) for key, value in (row.metadata_json or {}).items()},
        )

    @staticmethod
    def _copy_domain(row: CommissionLedgerEntryRecord, updated: CommissionLedgerEntry) -> None:
        row.contract_id = updated.contract_id
        row.status = updated.status.value
        row.metadata_json = updated.metadata
        row.updated_at = updated.updated_at

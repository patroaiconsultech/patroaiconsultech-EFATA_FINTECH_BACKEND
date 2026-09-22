from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import (
    CommissionLedgerEntryRecord,
    ReconciliationInboxRecord,
    ReconciliationOutboxRecord,
    ReconciliationReviewRecord,
)
from app.persistent_reconciliation import PersistentReconciliationService
from app.post_closing import CommissionStatus
from app.reconciliation_engine import ReconciliationDecision, SettlementEvent


def eligible_commission(service, ids, *, amount=Decimal("5000000"), contract_id="contract-1", invoice="INV-1"):
    with SessionLocal() as db:
        entry = service.register_commission(
            db,
            match_id="match-1",
            beneficiary_tenant_id=ids["platform_tenant"],
            trigger_event="CONTACT_RELEASED",
            base_amount=amount,
            rate_bps=75,
            contract_id=contract_id,
            metadata={"invoice_reference": invoice},
        )
        service.transition_commission(db, commission_id=entry.commission_id, status=CommissionStatus.CONTRACT_PENDING)
        service.transition_commission(db, commission_id=entry.commission_id, status=CommissionStatus.TRIGGER_PENDING)
        service.transition_commission(db, commission_id=entry.commission_id, status=CommissionStatus.ELIGIBLE)
        db.commit()
        return entry.commission_id


def settlement(*, amount=Decimal("37500.00"), event_id="bank-1", contract_id="contract-1", match_id="match-1", invoice="INV-1", source="BANK_SETTLEMENT_FEED"):
    return SettlementEvent(
        external_event_id=event_id,
        beneficiary_tenant_id="00000000-0000-0000-0000-000000000003",
        amount=amount,
        currency="BRL",
        settled_at=datetime.now(timezone.utc),
        contract_id=contract_id,
        match_id=match_id,
        invoice_reference=invoice,
        source=source,
    )


def test_persistent_exact_match_is_atomic_and_enqueues_outbox(ids):
    service = PersistentReconciliationService()
    commission_id = eligible_commission(service, ids)

    with SessionLocal() as db:
        result = service.reconcile(db, settlement())
        db.commit()
        row = db.get(CommissionLedgerEntryRecord, commission_id)
        outbox_count = db.scalar(select(func.count()).select_from(ReconciliationOutboxRecord))
        inbox_count = db.scalar(select(func.count()).select_from(ReconciliationInboxRecord))

    assert result.decision is ReconciliationDecision.AUTO_RECONCILED
    assert row.status == CommissionStatus.RECONCILED.value
    assert outbox_count == 1
    assert inbox_count == 1


def test_same_provider_event_is_idempotent(ids):
    service = PersistentReconciliationService()
    eligible_commission(service, ids)
    event = settlement(event_id="bank-duplicate")

    with SessionLocal() as db:
        first = service.reconcile(db, event)
        db.commit()
        second = service.reconcile(db, event)
        db.commit()
        inbox_count = db.scalar(select(func.count()).select_from(ReconciliationInboxRecord))
        link_count = db.scalar(select(func.count()).select_from(ReconciliationOutboxRecord))

    assert first.decision is ReconciliationDecision.AUTO_RECONCILED
    assert second.decision is ReconciliationDecision.DUPLICATE
    assert inbox_count == 1
    assert link_count == 1


def test_amount_variance_creates_open_review_and_acceptance_reconciles(ids):
    service = PersistentReconciliationService()
    commission_id = eligible_commission(service, ids)

    with SessionLocal() as db:
        result = service.reconcile(db, settlement(amount=Decimal("38000.00"), event_id="bank-variance"))
        db.commit()
        review = db.scalar(select(ReconciliationReviewRecord))
        initial_review_status = review.status
        claimed = service.claim_reviews(db, limit=10, actor_id=ids["analyst_user"])
        db.commit()
        resolved = service.resolve_review(
            db,
            review_id=review.review_id,
            actor_id=ids["analyst_user"],
            decision="ACCEPT_VARIANCE",
            notes="Diferença validada contra o aditivo contratual.",
        )
        db.commit()
        commission = db.get(CommissionLedgerEntryRecord, commission_id)
        outbox_count = db.scalar(select(func.count()).select_from(ReconciliationOutboxRecord))

    assert result.decision is ReconciliationDecision.REVIEW_REQUIRED
    assert initial_review_status == "OPEN"
    assert len(claimed) == 1
    assert resolved.status == "RESOLVED"
    assert commission.status == CommissionStatus.RECONCILED.value
    assert outbox_count == 1


def test_rejected_variance_marks_commission_disputed(ids):
    service = PersistentReconciliationService()
    commission_id = eligible_commission(service, ids)

    with SessionLocal() as db:
        service.reconcile(db, settlement(amount=Decimal("38000.00"), event_id="bank-reject"))
        db.commit()
        review = db.scalar(select(ReconciliationReviewRecord))
        resolved = service.resolve_review(
            db,
            review_id=review.review_id,
            actor_id=ids["analyst_user"],
            decision="REJECT_VARIANCE",
            notes="Valor não suportado pela documentação.",
        )
        db.commit()
        commission = db.get(CommissionLedgerEntryRecord, commission_id)

    assert resolved.status == "RESOLVED"
    assert commission.status == CommissionStatus.DISPUTED.value


def test_different_sources_can_reuse_external_event_id(ids):
    service = PersistentReconciliationService()
    eligible_commission(service, ids, contract_id="contract-a", invoice="INV-A")
    eligible_commission(service, ids, contract_id="contract-b", invoice="INV-B")

    with SessionLocal() as db:
        first = service.reconcile(db, settlement(event_id="same-id", contract_id="contract-a", invoice="INV-A", source="BANK_A"))
        db.commit()
        second = service.reconcile(db, settlement(event_id="same-id", contract_id="contract-b", invoice="INV-B", source="BANK_B"))
        db.commit()

    assert first.decision is ReconciliationDecision.AUTO_RECONCILED
    assert second.decision is ReconciliationDecision.AUTO_RECONCILED

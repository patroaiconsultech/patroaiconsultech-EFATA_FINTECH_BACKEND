from datetime import datetime, timezone
from decimal import Decimal

from app.post_closing import CommissionLedgerEntry, CommissionStatus
from app.reconciliation_engine import (
    CommissionReconciliationEngine,
    ReconciliationDecision,
    ReconciliationReason,
    SettlementEvent,
)


def eligible_entry(*, commission_id: str = "commission-1", invoice_reference: str = "INV-001"):
    entry = CommissionLedgerEntry.estimate(
        match_id="match-1",
        beneficiary_tenant_id="tenant-platform",
        trigger_event="CLOSED",
        base_amount=Decimal("5000000"),
        rate_bps=75,
        contract_id="contract-1",
    )
    entry = entry.__class__(
        commission_id=commission_id,
        match_id=entry.match_id,
        beneficiary_tenant_id=entry.beneficiary_tenant_id,
        contract_id=entry.contract_id,
        trigger_event=entry.trigger_event,
        base_amount=entry.base_amount,
        rate_bps=entry.rate_bps,
        estimated_amount=entry.estimated_amount,
        status=CommissionStatus.ELIGIBLE,
        currency=entry.currency,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        metadata={"invoice_reference": invoice_reference},
    )
    return entry


def settlement(**overrides):
    values = {
        "external_event_id": "settlement-1",
        "beneficiary_tenant_id": "tenant-platform",
        "amount": Decimal("37500.00"),
        "currency": "BRL",
        "settled_at": datetime(2026, 8, 21, tzinfo=timezone.utc),
        "contract_id": "contract-1",
        "match_id": "match-1",
        "invoice_reference": "INV-001",
    }
    values.update(overrides)
    return SettlementEvent(**values)


def test_exact_settlement_is_auto_reconciled_and_duplicate_is_idempotent():
    engine = CommissionReconciliationEngine()
    entry = eligible_entry()
    engine.add_commission(entry)

    first = engine.ingest_settlement(settlement())
    duplicate = engine.ingest_settlement(settlement())

    assert first.decision is ReconciliationDecision.AUTO_RECONCILED
    assert first.reason is ReconciliationReason.EXACT_REFERENCE_AND_AMOUNT
    assert engine.commission(entry.commission_id).status is CommissionStatus.RECONCILED
    assert duplicate.decision is ReconciliationDecision.DUPLICATE
    assert len(engine.results()) == 1


def test_amount_variance_requires_review_and_does_not_change_the_ledger():
    engine = CommissionReconciliationEngine()
    entry = eligible_entry()
    engine.add_commission(entry)

    result = engine.ingest_settlement(settlement(amount=Decimal("36000.00")))

    assert result.decision is ReconciliationDecision.REVIEW_REQUIRED
    assert result.reason is ReconciliationReason.AMOUNT_VARIANCE
    assert engine.commission(entry.commission_id).status is CommissionStatus.ELIGIBLE
    assert result.amount_variance == Decimal("1500.00")


def test_missing_strong_identity_requires_review():
    engine = CommissionReconciliationEngine()
    entry = eligible_entry()
    engine.add_commission(entry)

    result = engine.ingest_settlement(settlement(invoice_reference=None, match_id=None))

    assert result.decision is ReconciliationDecision.REVIEW_REQUIRED
    assert result.reason is ReconciliationReason.COMMISSION_NOT_READY
    assert engine.commission(entry.commission_id).status is CommissionStatus.ELIGIBLE


def test_unmatched_event_is_kept_for_operations():
    engine = CommissionReconciliationEngine()
    engine.add_commission(eligible_entry())

    result = engine.ingest_settlement(settlement(contract_id="other-contract", match_id="other-match", invoice_reference="INV-999"))

    assert result.decision is ReconciliationDecision.UNMATCHED
    assert result.reason is ReconciliationReason.NO_CANDIDATE
    assert result.commission_id is None


def test_commission_not_ready_is_not_auto_reconciled():
    engine = CommissionReconciliationEngine()
    entry = CommissionLedgerEntry.estimate(
        match_id="match-1",
        beneficiary_tenant_id="tenant-platform",
        trigger_event="CLOSED",
        base_amount=Decimal("5000000"),
        rate_bps=75,
        contract_id="contract-1",
    )
    entry = entry.__class__(
        commission_id=entry.commission_id,
        match_id=entry.match_id,
        beneficiary_tenant_id=entry.beneficiary_tenant_id,
        contract_id=entry.contract_id,
        trigger_event=entry.trigger_event,
        base_amount=entry.base_amount,
        rate_bps=entry.rate_bps,
        estimated_amount=entry.estimated_amount,
        status=CommissionStatus.TRIGGER_PENDING,
        currency=entry.currency,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        metadata={"invoice_reference": "INV-001"},
    )
    engine.add_commission(entry)

    result = engine.ingest_settlement(settlement())

    assert result.decision is ReconciliationDecision.REVIEW_REQUIRED
    assert result.reason is ReconciliationReason.COMMISSION_NOT_READY
    assert engine.commission(entry.commission_id).status is CommissionStatus.TRIGGER_PENDING

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.integrations.consent_ledger import ConsentLedger, ConsentStatus, ConsentViolation
from app.integrations.external_adapters import (
    AdapterRequest,
    BureauAdapter,
    DemoBureauAdapter,
    DemoOpenFinanceAdapter,
)
from app.post_closing import (
    CommissionStatus,
    InvalidTransition,
    MonitoringStatus,
    PostClosingLedger,
)


def make_consent(ledger: ConsentLedger):
    now = datetime.now(timezone.utc)
    return ledger.issue(
        subject_id="company-1",
        tenant_id="tenant-borrower",
        purpose="CREDIT_TRIAGE",
        scopes={"cashflow.read", "credit_operations.read"},
        recipient="efata",
        source_institution="bank-1",
        granted_at=now,
        expires_at=now + timedelta(days=30),
    )


def request_for(consent_id: str) -> AdapterRequest:
    return AdapterRequest(
        subject_id="company-1",
        tenant_id="tenant-borrower",
        consent_id=consent_id,
        purpose="CREDIT_TRIAGE",
        scopes=("cashflow.read",),
        request_id="request-1",
        correlation_id="correlation-1",
    )


def test_consent_is_checked_and_access_is_recorded():
    ledger = ConsentLedger()
    consent = make_consent(ledger)
    adapter = DemoOpenFinanceAdapter(consent_ledger=ledger)

    result = adapter.fetch(request_for(consent.consent_id))

    assert result.source_type == "OPEN_FINANCE"
    assert result.normalized_facts[0].provider == "demo-open-finance"
    assert result.evidence_hash.startswith("sha256:")
    assert len(ledger.access_events(consent.consent_id)) == 1


def test_revoked_consent_blocks_adapter_and_does_not_create_access_event():
    ledger = ConsentLedger()
    consent = make_consent(ledger)
    ledger.revoke(consent.consent_id)
    adapter = DemoOpenFinanceAdapter(consent_ledger=ledger)

    with pytest.raises(ConsentViolation):
        adapter.fetch(request_for(consent.consent_id))

    assert ledger.access_events(consent.consent_id) == []
    assert ledger.get(consent.consent_id).status is ConsentStatus.REVOKED


def test_adapter_can_normalize_a_provider_payload_without_provider_sdk():
    ledger = ConsentLedger()
    consent = make_consent(ledger)
    adapter = BureauAdapter(
        provider="bureau-contract-test",
        consent_ledger=ledger,
        fetcher=lambda request: {
            "source_period": "2026-07-31",
            "credit_score": 700,
            "open_defaults_count": 0,
            "quality": "VERIFIED",
        },
    )

    result = adapter.fetch(request_for(consent.consent_id))

    facts = {fact.fact: fact for fact in result.normalized_facts}
    assert facts["credit_score"].value == 700
    assert facts["credit_score"].quality == "VERIFIED"
    assert result.schema_version == "credit-bureau-evidence-v1"


def test_commission_ledger_requires_contract_before_eligibility():
    ledger = PostClosingLedger()
    entry = ledger.create_commission_estimate(
        match_id="match-1",
        beneficiary_tenant_id="tenant-platform",
        trigger_event="CLOSED",
        base_amount=Decimal("5000000"),
        rate_bps=75,
    )

    assert entry.estimated_amount == Decimal("37500.00")
    with pytest.raises(InvalidTransition):
        ledger.transition_commission(entry.commission_id, CommissionStatus.ELIGIBLE)

    ledger.transition_commission(
        entry.commission_id,
        CommissionStatus.CONTRACT_PENDING,
        contract_id="contract-1",
    )
    ledger.transition_commission(entry.commission_id, CommissionStatus.TRIGGER_PENDING)
    eligible = ledger.transition_commission(entry.commission_id, CommissionStatus.ELIGIBLE)
    assert eligible.status is CommissionStatus.ELIGIBLE
    assert eligible.contract_id == "contract-1"


def test_monitoring_items_can_be_due_and_completed_with_evidence():
    ledger = PostClosingLedger()
    item = ledger.add_monitoring_item(
        match_id="match-1",
        subject_tenant_id="tenant-borrower",
        kind="CONSENT_RENEWAL",
        due_date=date(2026, 8, 1),
    )

    assert item in ledger.due_items(as_of=date(2026, 8, 21))
    due = ledger.transition_monitoring(item.monitoring_id, MonitoringStatus.DUE)
    done = ledger.transition_monitoring(
        due.monitoring_id,
        MonitoringStatus.COMPLETED,
        last_evidence_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    assert done.status is MonitoringStatus.COMPLETED
    assert done.last_evidence_at is not None
    assert ledger.due_items(as_of=date(2026, 8, 21)) == []

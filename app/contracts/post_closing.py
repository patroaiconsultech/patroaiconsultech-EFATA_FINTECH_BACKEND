"""Typed API contracts for consent, external data and post-closing J/K flows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PostClosingApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConsentIssueRequest(BaseModel):
    subject_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=3, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=50)
    recipient: str = Field(min_length=2, max_length=128)
    source_institution: str = Field(min_length=2, max_length=255)
    expires_at: datetime
    provider_reference: str | None = Field(default=None, max_length=255)


class ConsentRevokeRequest(BaseModel):
    consent_id: str = Field(min_length=1, max_length=128)


class ConsentRead(PostClosingApiModel):
    consent_id: str
    subject_id: str
    tenant_id: str
    purpose: str
    scopes: list[str]
    recipient: str
    source_institution: str
    granted_at: datetime
    expires_at: datetime
    status: str
    provider_reference: str | None = None
    revoked_at: datetime | None = None


class ExternalDataRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=128)
    subject_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    consent_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=3, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=50)
    period_start: date | None = None
    period_end: date | None = None


class ExternalFactRead(BaseModel):
    fact: str
    value: Any
    unit: str | None
    as_of: str | None
    source: str
    provider: str
    quality: str
    evidence_hash: str


class ExternalDataRead(BaseModel):
    provider: str
    source_type: str
    request_id: str
    correlation_id: str
    retrieved_at: datetime
    source_period: str | None
    raw_reference: str
    normalized_facts: list[ExternalFactRead]
    quality_flags: list[str]
    errors: list[str]
    consent_id: str
    schema_version: str
    evidence_hash: str


class CommissionEstimateRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=128)
    beneficiary_tenant_id: str = Field(min_length=1, max_length=128)
    trigger_event: str = Field(min_length=3, max_length=128)
    base_amount: Decimal = Field(ge=0)
    rate_bps: int = Field(ge=0, le=10_000)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    contract_id: str | None = Field(default=None, max_length=128)


class CommissionTransitionRequest(BaseModel):
    status: str = Field(min_length=3, max_length=32)
    contract_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, str] = Field(default_factory=dict)


class CommissionLedgerRead(PostClosingApiModel):
    commission_id: str
    match_id: str
    beneficiary_tenant_id: str
    contract_id: str | None
    trigger_event: str
    base_amount: Decimal
    rate_bps: int
    estimated_amount: Decimal
    status: str
    currency: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, str]


class MonitoringCreateRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=128)
    subject_tenant_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=3, max_length=128)
    due_date: date
    owner_agent: str = Field(default="GOVERNANCE_AGENT", min_length=3, max_length=128)
    source: str = Field(default="POST_CLOSING_CONTRACT", min_length=3, max_length=128)
    evidence_required: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)


class MonitoringTransitionRequest(BaseModel):
    status: str = Field(min_length=3, max_length=32)
    last_evidence_at: datetime | None = None


class MonitoringRead(PostClosingApiModel):
    monitoring_id: str
    match_id: str
    subject_tenant_id: str
    kind: str
    due_date: date
    status: str
    owner_agent: str
    source: str
    evidence_required: bool
    last_evidence_at: datetime | None
    metadata: dict[str, str]


class SettlementEventRequest(BaseModel):
    external_event_id: str = Field(min_length=1, max_length=255)
    beneficiary_tenant_id: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(ge=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    settled_at: datetime
    contract_id: str | None = Field(default=None, max_length=128)
    match_id: str | None = Field(default=None, max_length=128)
    invoice_reference: str | None = Field(default=None, max_length=255)
    account_fingerprint: str | None = Field(default=None, max_length=255)
    source: str = Field(default="BANK_SETTLEMENT_FEED", min_length=3, max_length=128)
    metadata: dict[str, str] = Field(default_factory=dict)


class ReconciliationResultRead(BaseModel):
    reconciliation_id: str
    external_event_id: str
    decision: str
    reason: str
    commission_id: str | None
    candidate_commission_ids: list[str]
    amount_variance: Decimal | None
    policy_version: str
    reconciled_at: datetime
    detail: dict[str, str]


class ReconciliationBatchRead(BaseModel):
    processed: int
    auto_reconciled: int
    review_required: int
    unmatched: int
    duplicates: int
    results: list[ReconciliationResultRead]


class ReviewClaimRequest(BaseModel):
    assigned_to: str | None = Field(default=None, max_length=128)


class ReviewResolveRequest(BaseModel):
    decision: str = Field(min_length=3, max_length=32)
    notes: str = Field(min_length=3, max_length=2000)


class ReconciliationReviewRead(PostClosingApiModel):
    review_id: str
    inbox_id: str
    link_id: str | None
    status: str
    reason: str
    expected_amount: Decimal | None
    received_amount: Decimal
    amount_variance: Decimal | None
    currency: str
    assigned_to: str | None
    decision: str | None
    notes: str | None
    due_at: datetime | None
    created_at: datetime
    resolved_at: datetime | None


class ReconciliationOutboxRead(PostClosingApiModel):
    outbox_id: str
    event_key: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    status: str
    attempt_count: int
    available_at: datetime
    created_at: datetime
    published_at: datetime | None
    claimed_at: datetime | None = None
    lease_until: datetime | None = None
    last_attempt_at: datetime | None = None
    failed_at: datetime | None = None
    dead_lettered_at: datetime | None = None
    last_error: str | None


class OutboxMetricsRead(BaseModel):
    captured_at: datetime
    pending_count: int
    processing_count: int
    published_count: int
    dead_letter_count: int
    retry_total: int
    oldest_pending_age_seconds: float
    oldest_processing_age_seconds: float
    overdue_processing_count: int
    published_last_24h: int
    failed_last_24h: int
    alerts: list[str]


class ConsentLedgerIntegrityRead(BaseModel):
    tenant_id: str
    valid: bool
    event_count: int
    last_sequence: int
    last_hash: str
    failed_event_id: str | None = None

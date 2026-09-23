from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "iam_users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Organization(Base):
    __tablename__ = "iam_organizations"

    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Tenant(Base):
    __tablename__ = "iam_tenants"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("iam_organizations.organization_id"), nullable=False)
    tenant_type: Mapped[str] = mapped_column(String(64), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Membership(Base):
    __tablename__ = "iam_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_membership_user_tenant"),
    )

    membership_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Lead(Base):
    __tablename__ = "deals_leads"

    lead_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    prospective_client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RepresentationAuthorization(Base):
    __tablename__ = "deals_representation_authorizations"

    authorization_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    originator_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    represented_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    lead_id: Mapped[str] = mapped_column(ForeignKey("deals_leads.lead_id"), nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(ForeignKey("iam_users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapitalOpportunity(Base):
    __tablename__ = "deals_capital_opportunities"

    opportunity_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    source_lead_id: Mapped[str] = mapped_column(ForeignKey("deals_leads.lead_id"), nullable=False)
    representation_authorization_id: Mapped[str] = mapped_column(
        ForeignKey("deals_representation_authorizations.authorization_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResourceGrant(Base):
    __tablename__ = "core_resource_access_grants"
    __table_args__ = (
        UniqueConstraint(
            "grantee_tenant_id",
            "resource_type",
            "resource_id",
            "source_type",
            "source_id",
            name="uq_grant_resource_source",
        ),
        Index(
            "ix_grant_access_lookup",
            "grantee_tenant_id",
            "resource_type",
            "resource_id",
            "status",
        ),
        Index(
            "ix_grant_source_lookup",
            "source_type",
            "source_id",
            "status",
        ),
    )

    grant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    grantee_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Document(Base):
    __tablename__ = "documents_documents"

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("deals_capital_opportunities.opportunity_id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="MOCK_ACCEPTED")
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class QualificationCase(Base):
    __tablename__ = "deals_qualification_cases"

    qualification_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("deals_capital_opportunities.opportunity_id"), nullable=False)
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "platform_audit_events"

    audit_event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BorrowerProfile(Base):
    __tablename__ = "marketplace_borrower_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_borrower_profile_tenant"),)

    borrower_profile_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    segment: Mapped[str] = mapped_column(String(64), nullable=False)
    sectors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    group_profile: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class FundingProvider(Base):
    __tablename__ = "marketplace_funding_providers"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_funding_provider_tenant"),)

    funding_provider_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mandate_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class FundingProduct(Base):
    __tablename__ = "marketplace_funding_products"
    __table_args__ = (
        Index("ix_funding_product_status", "status"),
        Index("ix_funding_product_provider", "funding_provider_id"),
    )

    funding_product_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    funding_provider_id: Mapped[str] = mapped_column(
        ForeignKey("marketplace_funding_providers.funding_provider_id"), nullable=False
    )
    provider_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    min_ticket: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    max_ticket: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    min_term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    max_term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_collateral_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sectors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    stage_requirements: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    indicative_terms: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PartnerProfile(Base):
    __tablename__ = "marketplace_partner_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_partner_profile_tenant"),)

    partner_profile_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    partner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    focus_regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    commercial_terms: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CreditRequest(Base):
    __tablename__ = "marketplace_credit_requests"
    __table_args__ = (
        Index("ix_credit_request_owner_status", "owner_tenant_id", "status"),
        Index("ix_credit_request_partner", "source_partner_tenant_id"),
    )

    credit_request_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    borrower_profile_id: Mapped[str] = mapped_column(
        ForeignKey("marketplace_borrower_profiles.borrower_profile_id"), nullable=False
    )
    source_partner_tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("iam_tenants.tenant_id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    credit_type: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    grace_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collateral_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sectors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    project_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    consent_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Match(Base):
    __tablename__ = "marketplace_matches"
    __table_args__ = (
        UniqueConstraint("credit_request_id", "funding_product_id", name="uq_match_request_product"),
        Index("ix_match_funder_status", "funder_tenant_id", "status"),
        Index("ix_match_agent_status", "assigned_agent_id", "status"),
    )

    match_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    credit_request_id: Mapped[str] = mapped_column(
        ForeignKey("marketplace_credit_requests.credit_request_id"), nullable=False
    )
    funding_product_id: Mapped[str] = mapped_column(
        ForeignKey("marketplace_funding_products.funding_product_id"), nullable=False
    )
    borrower_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    funder_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUGGESTED")
    assigned_agent_id: Mapped[str | None] = mapped_column(ForeignKey("iam_users.user_id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MatchEvent(Base):
    __tablename__ = "marketplace_match_events"

    match_event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    match_id: Mapped[str] = mapped_column(ForeignKey("marketplace_matches.match_id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CommissionEvent(Base):
    __tablename__ = "marketplace_commission_events"

    commission_event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    match_id: Mapped[str] = mapped_column(ForeignKey("marketplace_matches.match_id"), nullable=False, index=True)
    beneficiary_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ESTIMATE")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CreditRequestDocument(Base):
    __tablename__ = "marketplace_credit_request_documents"
    __table_args__ = (Index("ix_credit_request_document_request", "credit_request_id"),)

    credit_request_document_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    credit_request_id: Mapped[str] = mapped_column(
        ForeignKey("marketplace_credit_requests.credit_request_id"), nullable=False
    )
    owner_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="MOCK_ACCEPTED")
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RiskAssessment(Base):
    __tablename__ = "marketplace_risk_assessments"
    __table_args__ = (
        Index("ix_risk_assessment_request_created", "credit_request_id", "created_at"),
        Index("ix_risk_assessment_decision", "decision", "human_status"),
    )

    assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    credit_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("marketplace_credit_requests.credit_request_id"), nullable=True, index=True
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(48), nullable=False)
    risk_band: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    rule_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    missing_data: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    hard_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    soft_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    human_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MatchGovernanceReview(Base):
    __tablename__ = "marketplace_match_governance_reviews"
    __table_args__ = (
        Index(
            "ix_marketplace_match_governance_reviews_match_id",
            "match_id",
        ),
        Index(
            "ix_governance_review_match_created",
            "match_id",
            "created_at",
        ),
    )

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    match_id: Mapped[str] = mapped_column(ForeignKey("marketplace_matches.match_id"), nullable=False)
    assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("marketplace_risk_assessments.assessment_id"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(48), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CommissionLedgerEntryRecord(Base):
    __tablename__ = "post_closing_commission_ledger"
    __table_args__ = (
        Index("ix_commission_ledger_beneficiary_status", "beneficiary_tenant_id", "status"),
        Index("ix_commission_ledger_match", "match_id"),
        Index("ix_commission_ledger_contract", "contract_id"),
    )

    commission_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("marketplace_matches.match_id"), nullable=False)
    beneficiary_tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    contract_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger_event: Mapped[str] = mapped_column(String(128), nullable=False)
    base_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ESTIMATE_ONLY")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ReconciliationInboxRecord(Base):
    __tablename__ = "post_closing_reconciliation_inbox"
    __table_args__ = (
        UniqueConstraint("source", "external_event_id", name="uq_reconciliation_inbox_source_event"),
        Index("ix_reconciliation_inbox_status_received", "status", "received_at"),
    )

    inbox_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReconciliationOutboxRecord(Base):
    __tablename__ = "post_closing_reconciliation_outbox"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_reconciliation_outbox_event_key"),
        Index("ix_reconciliation_outbox_status_available", "status", "available_at"),
    )

    outbox_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReconciliationLinkRecord(Base):
    __tablename__ = "post_closing_reconciliation_links"
    __table_args__ = (
        UniqueConstraint("inbox_id", name="uq_reconciliation_link_inbox"),
        UniqueConstraint("commission_id", "inbox_id", name="uq_reconciliation_link_pair"),
        Index("ix_reconciliation_link_commission", "commission_id"),
    )

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    inbox_id: Mapped[str] = mapped_column(ForeignKey("post_closing_reconciliation_inbox.inbox_id"), nullable=False)
    commission_id: Mapped[str | None] = mapped_column(ForeignKey("post_closing_commission_ledger.commission_id"), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_variance: Mapped[float | None] = mapped_column(Numeric(19, 4), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ReconciliationReviewRecord(Base):
    __tablename__ = "post_closing_reconciliation_reviews"
    __table_args__ = (
        UniqueConstraint("inbox_id", name="uq_reconciliation_review_inbox"),
        Index("ix_reconciliation_review_status_due", "status", "due_at"),
        Index("ix_reconciliation_review_assignee", "assigned_to", "status"),
    )

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    inbox_id: Mapped[str] = mapped_column(ForeignKey("post_closing_reconciliation_inbox.inbox_id"), nullable=False)
    link_id: Mapped[str | None] = mapped_column(ForeignKey("post_closing_reconciliation_links.link_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_amount: Mapped[float | None] = mapped_column(Numeric(19, 4), nullable=True)
    received_amount: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False)
    amount_variance: Mapped[float | None] = mapped_column(Numeric(19, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("iam_users.user_id"), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsentLedgerHeadRecord(Base):
    __tablename__ = "consent_ledger_heads"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="GENESIS")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ConsentGrantRecord(Base):
    __tablename__ = "consent_ledger_grants"
    __table_args__ = (
        Index("ix_consent_grant_subject_status", "tenant_id", "subject_ref", "status"),
        Index("ix_consent_grant_expiry", "status", "expires_at"),
    )

    consent_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    source_institution: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ConsentLedgerEventRecord(Base):
    __tablename__ = "consent_ledger_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sequence_no", name="uq_consent_ledger_tenant_sequence"),
        UniqueConstraint("event_hash", name="uq_consent_ledger_event_hash"),
        Index("ix_consent_ledger_consent_time", "consent_id", "occurred_at"),
        Index("ix_consent_ledger_type_time", "event_type", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    consent_id: Mapped[str | None] = mapped_column(ForeignKey("consent_ledger_grants.consent_id"), nullable=True)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column("payload", JSON, nullable=False, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ViabilityStudy(Base):
    __tablename__ = "viability_studies"
    __table_args__ = (
        Index("ix_viability_study_tenant_status", "tenant_id", "status"),
        Index("ix_viability_study_opportunity", "opportunity_id"),
    )

    study_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False, index=True)
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("marketplace_credit_requests.credit_request_id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False, default="M0_DRAFT")
    base_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ViabilityScenario(Base):
    __tablename__ = "viability_scenarios"
    __table_args__ = (
        UniqueConstraint("study_id", "scenario_key", name="uq_viability_scenario_key"),
        Index("ix_viability_scenario_study_status", "study_id", "status"),
    )

    scenario_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("viability_studies.study_id"), nullable=False, index=True)
    scenario_key: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    overrides_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    outputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False, default="m1-fcd-v1")
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ViabilityMonthlyFlow(Base):
    __tablename__ = "viability_monthly_flows"
    __table_args__ = (
        UniqueConstraint("scenario_id", "period_start", name="uq_viability_scenario_period"),
        Index("ix_viability_monthly_flow_scenario", "scenario_id", "period_start"),
    )

    flow_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("viability_scenarios.scenario_id"), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revenue: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    equity_contribution: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    funding_draw: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    land_cost: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    construction_cost: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    other_costs: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    interest: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    principal: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    net_cash_flow: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    cumulative_cash_flow: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    discount_factor: Mapped[float] = mapped_column(Numeric(19, 10), nullable=False, default=1)
    present_value: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    project_cash_flow: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    debt_balance: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    unlevered_present_value: Mapped[float] = mapped_column(Numeric(19, 4), nullable=False, default=0)


class ViabilitySnapshot(Base):
    __tablename__ = "viability_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_hash", name="uq_viability_snapshot_hash"),
        Index("ix_viability_snapshot_study_created", "study_id", "created_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("viability_studies.study_id"), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("viability_scenarios.scenario_id"), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="READY")


class ERPConnection(Base):
    __tablename__ = "integration_erp_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_tenant", name="uq_erp_connection_tenant_provider"),
        Index("ix_erp_connection_tenant_status", "tenant_id", "status"),
    )

    connection_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_tenant: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    resource_map_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    secret_key_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("iam_users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationSyncJob(Base):
    __tablename__ = "integration_sync_jobs"
    __table_args__ = (
        Index(
            "ix_sync_job_connection_created",
            "connection_id",
            "created_at",
        ),
        Index(
            "ix_sync_job_study_created",
            "study_id",
            "created_at",
        ),
    )

    sync_job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_erp_connections.connection_id"), nullable=False)
    study_id: Mapped[str | None] = mapped_column(ForeignKey("viability_studies.study_id"), nullable=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("iam_tenants.tenant_id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="READ_ONLY")
    cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LeadCreate(BaseModel):
    prospective_client_name: str = Field(min_length=2, max_length=255)
    opportunity_type: str = Field(min_length=2, max_length=64)
    estimated_amount: Decimal = Field(gt=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)


class LeadRead(ApiModel):
    lead_id: str
    tenant_id: str
    prospective_client_name: str
    opportunity_type: str
    estimated_amount: Decimal
    currency: str
    status: str


class RepresentationCreate(BaseModel):
    lead_id: str
    represented_tenant_id: str
    allowed_actions: list[str] = Field(default_factory=lambda: [
        "CREATE_OPPORTUNITY",
        "UPLOAD_DOCUMENTS",
        "VIEW_STATUS",
    ])


class RepresentationRead(ApiModel):
    authorization_id: str
    originator_tenant_id: str
    represented_tenant_id: str
    lead_id: str
    allowed_actions: list[str]
    status: str


class OpportunityCreate(BaseModel):
    representation_authorization_id: str
    title: str = Field(min_length=3, max_length=255)
    purpose: str = Field(min_length=3, max_length=4000)


class OpportunityRead(ApiModel):
    opportunity_id: str
    tenant_id: str
    title: str
    opportunity_type: str
    requested_amount: Decimal
    currency: str
    purpose: str
    stage: str
    version: int


class DocumentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=2, max_length=64)
    checksum_sha256: str = Field(min_length=64, max_length=64)


class DocumentRead(ApiModel):
    document_id: str
    tenant_id: str
    opportunity_id: str
    filename: str
    document_type: str
    storage_key: str
    processing_status: str


class QualificationCreate(BaseModel):
    result: str = Field(pattern="^(ELIGIBLE|CONDITIONALLY_ELIGIBLE|INFORMATION_REQUIRED|NOT_ELIGIBLE)$")
    conclusion: str = Field(min_length=3, max_length=4000)


class QualificationRead(ApiModel):
    qualification_id: str
    tenant_id: str
    opportunity_id: str
    result: str
    conclusion: str


class BorrowerProfileCreate(BaseModel):
    segment: str = Field(min_length=2, max_length=64)
    sectors: list[str] = Field(default_factory=list, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    group_profile: dict = Field(default_factory=dict)


class BorrowerProfileRead(ApiModel):
    borrower_profile_id: str
    tenant_id: str
    segment: str
    sectors: list[str]
    regions: list[str]
    group_profile: dict
    status: str


class FundingProviderCreate(BaseModel):
    provider_type: str = Field(pattern="^(FUND|BANK|SECURITIZER|FAMILY_OFFICE|OTHER)$")
    legal_name: str = Field(min_length=2, max_length=255)
    website: str | None = Field(default=None, max_length=512)
    mandate_summary: str = Field(min_length=3, max_length=4000)


class FundingProviderRead(ApiModel):
    funding_provider_id: str
    tenant_id: str
    provider_type: str
    legal_name: str
    website: str | None
    mandate_summary: str
    status: str


class FundingProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    product_type: str = Field(min_length=2, max_length=64)
    min_ticket: Decimal = Field(gt=0)
    max_ticket: Decimal = Field(gt=0)
    min_term_months: int = Field(ge=1, le=600)
    max_term_months: int = Field(ge=1, le=600)
    allowed_collateral_types: list[str] = Field(default_factory=list, max_length=20)
    sectors: list[str] = Field(default_factory=list, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    stage_requirements: list[str] = Field(default_factory=list, max_length=20)
    indicative_terms: dict = Field(default_factory=dict)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    status: str = Field(default="DRAFT", pattern="^(DRAFT|UNDER_REVIEW|ACTIVE|PAUSED|ARCHIVED)$")


class FundingProductRead(ApiModel):
    funding_product_id: str
    funding_provider_id: str
    provider_tenant_id: str
    name: str
    product_type: str
    min_ticket: Decimal
    max_ticket: Decimal
    min_term_months: int
    max_term_months: int
    allowed_collateral_types: list[str]
    sectors: list[str]
    regions: list[str]
    stage_requirements: list[str]
    indicative_terms: dict
    currency: str
    status: str


class PartnerProfileCreate(BaseModel):
    partner_type: str = Field(min_length=2, max_length=64)
    focus_regions: list[str] = Field(default_factory=list, max_length=20)
    commercial_terms: dict = Field(default_factory=dict)


class PartnerProfileRead(ApiModel):
    partner_profile_id: str
    tenant_id: str
    partner_type: str
    focus_regions: list[str]
    commercial_terms: dict
    status: str


class CreditRequestCreate(BaseModel):
    borrower_profile_id: str
    source_partner_tenant_id: str | None = None
    title: str = Field(min_length=3, max_length=255)
    credit_type: str = Field(min_length=2, max_length=64)
    requested_amount: Decimal = Field(gt=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    term_months: int = Field(ge=1, le=600)
    grace_months: int = Field(default=0, ge=0, le=120)
    collateral_types: list[str] = Field(default_factory=list, max_length=20)
    sectors: list[str] = Field(default_factory=list, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    project_stage: str = Field(min_length=2, max_length=64)
    purpose: str = Field(min_length=3, max_length=4000)
    consent_status: str = Field(default="PENDING", pattern="^(PENDING|GRANTED|REVOKED)$")
    status: str = Field(default="DRAFT", pattern="^(DRAFT|SUBMITTED|TRIAGE|INFORMATION_REQUIRED|QUALIFIED|MATCHING)$")


class CreditRequestRead(ApiModel):
    credit_request_id: str
    owner_tenant_id: str
    borrower_profile_id: str
    source_partner_tenant_id: str | None
    title: str
    credit_type: str
    requested_amount: Decimal
    currency: str
    term_months: int
    grace_months: int
    collateral_types: list[str]
    sectors: list[str]
    regions: list[str]
    project_stage: str
    purpose: str
    consent_status: str
    status: str
    version: int


class MatchRead(ApiModel):
    match_id: str
    credit_request_id: str
    funding_product_id: str
    borrower_tenant_id: str
    funder_tenant_id: str
    score: int
    eligible: bool
    reasons: list[str]
    gaps: list[str]
    status: str
    assigned_agent_id: str | None


class MatchStatusUpdate(BaseModel):
    status: str = Field(
        pattern="^(AGENT_REVIEW|APPROVED_TO_CONTACT|SENT|INTERESTED|DILIGENCE|NEGOTIATION|CONVERTED|DECLINED|EXPIRED|BLOCKED)$"
    )
    reason: str = Field(min_length=3, max_length=2000)
    visibility: str = Field(default="INTERNAL", pattern="^(INTERNAL|BORROWER|FUNDER|PARTNER)$")


class CommissionEventCreate(BaseModel):
    match_id: str
    beneficiary_tenant_id: str
    event_type: str = Field(min_length=2, max_length=64)
    base_amount: Decimal = Field(ge=0)
    rate_bps: int = Field(default=0, ge=0, le=10000)


class CommissionEventRead(ApiModel):
    commission_event_id: str
    match_id: str
    beneficiary_tenant_id: str
    event_type: str
    base_amount: Decimal
    rate_bps: int
    estimated_amount: Decimal
    status: str


class CreditRequestDocumentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=2, max_length=64)
    checksum_sha256: str = Field(min_length=64, max_length=64)


class CreditRequestDocumentRead(ApiModel):
    credit_request_document_id: str
    credit_request_id: str
    owner_tenant_id: str
    filename: str
    document_type: str
    storage_key: str
    checksum_sha256: str
    processing_status: str


class AgentRead(BaseModel):
    key: str
    name: str
    specialty: str
    description: str
    queue: str
    autonomy: str
    next_action: str
    human_review_required: bool
    open_items: int = 0


class RiskSimulationInput(BaseModel):
    credit_request_id: str | None = None
    consent_status: str = Field(default="GRANTED", pattern="^(PENDING|GRANTED|REVOKED)$")
    requested_amount: Decimal = Field(gt=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    term_months: int = Field(ge=1, le=600)
    project_stage: str = Field(min_length=2, max_length=64)
    purpose: str = Field(min_length=3, max_length=4000)
    collateral_types: list[str] = Field(default_factory=list, max_length=20)
    sectors: list[str] = Field(default_factory=list, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    document_types: list[str] = Field(default_factory=list, max_length=20)
    revenue_monthly: Decimal | None = Field(default=None, ge=0)
    debt_service_monthly: Decimal | None = Field(default=None, ge=0)
    ebitda_annual: Decimal | None = Field(default=None, ge=0)
    total_debt: Decimal | None = Field(default=None, ge=0)
    collateral_value: Decimal | None = Field(default=None, ge=0)
    dscr: Decimal | None = Field(default=None, ge=0)
    ltv: Decimal | None = Field(default=None, ge=0)
    financial_data_confidence: str = Field(default="MISSING", pattern="^(HIGH|MEDIUM|LOW|MISSING)$")


class RiskRuleRead(BaseModel):
    rule_key: str
    label: str
    status: str
    value: object | None
    threshold: object | None
    source: str
    explanation: str
    score_contribution: int


class RiskAssessmentRead(ApiModel):
    assessment_id: str
    credit_request_id: str | None
    policy_version: str
    decision: str
    risk_band: str
    score: int
    recommendation: str
    rule_results: list[RiskRuleRead]
    evidence: list[dict]
    missing_data: list[str]
    hard_flags: list[str]
    soft_flags: list[str]
    human_status: str
    created_by: str
    created_at: object


class GovernanceReviewCreate(BaseModel):
    assessment_id: str | None = None
    decision: str = Field(pattern="^(APPROVE_CONTACT|REQUEST_INFORMATION|BLOCK|REJECT)$")
    reason: str = Field(min_length=5, max_length=2000)
    visibility: str = Field(default="INTERNAL", pattern="^(INTERNAL|BORROWER|FUNDER|PARTNER)$")


class GovernanceReviewRead(ApiModel):
    review_id: str
    match_id: str
    assessment_id: str | None
    decision: str
    reason: str
    actor_id: str
    created_at: object


class GovernanceQueueItemRead(BaseModel):
    match_id: str
    credit_request_id: str
    funding_product_id: str
    score: int
    eligible: bool
    match_status: str
    risk_assessment: RiskAssessmentRead | None = None
    latest_review: GovernanceReviewRead | None = None
    requires_human_decision: bool

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.errors import ApiError
from app.agent_registry import AGENT_REGISTRY
from app.matching import evaluate_match
from app.models import (
    BorrowerProfile,
    CommissionEvent,
    CreditRequest,
    CreditRequestDocument,
    FundingProduct,
    FundingProvider,
    Match,
    MatchEvent,
    PartnerProfile,
    Tenant,
)
from app.schemas import (
    AgentRead,
    BorrowerProfileCreate,
    BorrowerProfileRead,
    CommissionEventCreate,
    CommissionEventRead,
    CreditRequestCreate,
    CreditRequestDocumentCreate,
    CreditRequestDocumentRead,
    CreditRequestRead,
    FundingProductCreate,
    FundingProductRead,
    FundingProviderCreate,
    FundingProviderRead,
    MatchRead,
    MatchStatusUpdate,
    PartnerProfileCreate,
    PartnerProfileRead,
)
from app.security import SecurityContext, require_security_context

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])


@router.get("/agents", response_model=list[AgentRead])
def list_internal_agents(
    context: SecurityContext = Depends(require_security_context),
) -> list[AgentRead]:
    _require_role(context, INTERNAL_ROLES)
    return [AgentRead(**agent.__dict__) for agent in AGENT_REGISTRY]


INTERNAL_ROLES = {"ANALYST", "PLATFORM_ADMIN", "INTERNAL_AGENT", "CREDIT_ANALYST"}
BORROWER_ROLES = {"ORIGINATOR_ADMIN", "CLIENT_ADMIN", "BORROWER_ADMIN", "BORROWER_EDITOR"}
FUNDER_ROLES = {"FUNDER_ADMIN", "FUNDER_EDITOR", "INVESTOR_ANALYST"}
PARTNER_ROLES = {"PARTNER_ADMIN", "PARTNER_EDITOR"}


def _require_role(context: SecurityContext, roles: set[str]) -> SecurityContext:
    if context.role not in roles:
        raise ApiError(403, "ROLE_NOT_ALLOWED", "Acesso não autorizado.")
    return context


def _is_internal(context: SecurityContext) -> bool:
    return context.role in INTERNAL_ROLES


def _audit(db: Session, request: Request, context: SecurityContext, action: str, resource_type: str, resource_id: str) -> None:
    record_audit(
        db,
        context=context,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
    )


@router.post("/borrower-profiles", response_model=BorrowerProfileRead, status_code=201)
def create_borrower_profile(
    payload: BorrowerProfileCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> BorrowerProfile:
    _require_role(context, BORROWER_ROLES | PARTNER_ROLES | INTERNAL_ROLES)
    existing = db.scalar(select(BorrowerProfile).where(BorrowerProfile.tenant_id == context.tenant_id))
    if existing is not None:
        raise ApiError(409, "BORROWER_PROFILE_EXISTS", "O tenant já possui um perfil de tomador.")
    profile = BorrowerProfile(
        tenant_id=context.tenant_id,
        segment=payload.segment,
        sectors=payload.sectors,
        regions=payload.regions,
        group_profile=payload.group_profile,
        created_by=context.user_id,
    )
    db.add(profile)
    db.flush()
    _audit(db, request, context, "BORROWER_PROFILE_CREATED", "BORROWER_PROFILE", profile.borrower_profile_id)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/borrower-profiles", response_model=list[BorrowerProfileRead])
def list_borrower_profiles(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[BorrowerProfile]:
    query = select(BorrowerProfile)
    if not _is_internal(context):
        query = query.where(BorrowerProfile.tenant_id == context.tenant_id)
    return list(db.scalars(query.order_by(BorrowerProfile.created_at.desc())).all())


@router.post("/funding-providers", response_model=FundingProviderRead, status_code=201)
def create_funding_provider(
    payload: FundingProviderCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> FundingProvider:
    _require_role(context, FUNDER_ROLES | INTERNAL_ROLES)
    existing = db.scalar(select(FundingProvider).where(FundingProvider.tenant_id == context.tenant_id))
    if existing is not None:
        raise ApiError(409, "FUNDING_PROVIDER_EXISTS", "O tenant já possui um perfil de funding.")
    provider = FundingProvider(
        tenant_id=context.tenant_id,
        provider_type=payload.provider_type,
        legal_name=payload.legal_name,
        website=payload.website,
        mandate_summary=payload.mandate_summary,
        created_by=context.user_id,
    )
    db.add(provider)
    db.flush()
    _audit(db, request, context, "FUNDING_PROVIDER_CREATED", "FUNDING_PROVIDER", provider.funding_provider_id)
    db.commit()
    db.refresh(provider)
    return provider


@router.get("/funding-providers", response_model=list[FundingProviderRead])
def list_funding_providers(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[FundingProvider]:
    query = select(FundingProvider)
    if not _is_internal(context):
        query = query.where(FundingProvider.tenant_id == context.tenant_id)
    return list(db.scalars(query.order_by(FundingProvider.created_at.desc())).all())


@router.post("/funding-products", response_model=FundingProductRead, status_code=201)
def create_funding_product(
    payload: FundingProductCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> FundingProduct:
    _require_role(context, FUNDER_ROLES | INTERNAL_ROLES)
    provider = db.scalar(select(FundingProvider).where(FundingProvider.tenant_id == context.tenant_id))
    if provider is None:
        raise ApiError(409, "FUNDING_PROVIDER_REQUIRED", "Cadastre o perfil de funding antes do produto.")
    if payload.max_ticket < payload.min_ticket or payload.max_term_months < payload.min_term_months:
        raise ApiError(422, "INVALID_PRODUCT_RANGE", "A faixa máxima deve ser maior ou igual à mínima.")
    product = FundingProduct(
        funding_provider_id=provider.funding_provider_id,
        provider_tenant_id=context.tenant_id,
        name=payload.name,
        product_type=payload.product_type,
        min_ticket=payload.min_ticket,
        max_ticket=payload.max_ticket,
        min_term_months=payload.min_term_months,
        max_term_months=payload.max_term_months,
        allowed_collateral_types=payload.allowed_collateral_types,
        sectors=payload.sectors,
        regions=payload.regions,
        stage_requirements=payload.stage_requirements,
        indicative_terms=payload.indicative_terms,
        currency=payload.currency.upper(),
        status=payload.status,
        created_by=context.user_id,
    )
    db.add(product)
    db.flush()
    _audit(db, request, context, "FUNDING_PRODUCT_CREATED", "FUNDING_PRODUCT", product.funding_product_id)
    db.commit()
    db.refresh(product)
    return product


@router.get("/funding-products", response_model=list[FundingProductRead])
def list_funding_products(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[FundingProduct]:
    query = select(FundingProduct)
    if not _is_internal(context):
        query = query.where(FundingProduct.provider_tenant_id == context.tenant_id)
    return list(db.scalars(query.order_by(FundingProduct.created_at.desc())).all())


@router.post("/partners", response_model=PartnerProfileRead, status_code=201)
def create_partner_profile(
    payload: PartnerProfileCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> PartnerProfile:
    _require_role(context, PARTNER_ROLES | INTERNAL_ROLES)
    existing = db.scalar(select(PartnerProfile).where(PartnerProfile.tenant_id == context.tenant_id))
    if existing is not None:
        raise ApiError(409, "PARTNER_PROFILE_EXISTS", "O tenant já possui um perfil de parceiro.")
    profile = PartnerProfile(
        tenant_id=context.tenant_id,
        partner_type=payload.partner_type,
        focus_regions=payload.focus_regions,
        commercial_terms=payload.commercial_terms,
        created_by=context.user_id,
    )
    db.add(profile)
    db.flush()
    _audit(db, request, context, "PARTNER_PROFILE_CREATED", "PARTNER_PROFILE", profile.partner_profile_id)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/partners", response_model=list[PartnerProfileRead])
def list_partner_profiles(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[PartnerProfile]:
    query = select(PartnerProfile)
    if not _is_internal(context):
        query = query.where(PartnerProfile.tenant_id == context.tenant_id)
    return list(db.scalars(query.order_by(PartnerProfile.created_at.desc())).all())


@router.post("/credit-requests", response_model=CreditRequestRead, status_code=201)
def create_credit_request(
    payload: CreditRequestCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CreditRequest:
    _require_role(context, BORROWER_ROLES | PARTNER_ROLES | INTERNAL_ROLES)
    profile = db.scalar(
        select(BorrowerProfile).where(
            BorrowerProfile.borrower_profile_id == payload.borrower_profile_id,
            BorrowerProfile.status == "ACTIVE",
        )
    )
    if profile is None:
        raise ApiError(404, "BORROWER_PROFILE_NOT_FOUND", "Perfil de tomador não encontrado.")
    if not _is_internal(context) and profile.tenant_id != context.tenant_id:
        raise ApiError(403, "BORROWER_PROFILE_NOT_ALLOWED", "Perfil fora do escopo do tenant.")
    if payload.source_partner_tenant_id:
        partner_profile = db.scalar(
            select(PartnerProfile).where(
                PartnerProfile.tenant_id == payload.source_partner_tenant_id,
                PartnerProfile.status == "ACTIVE",
            )
        )
        if partner_profile is None:
            raise ApiError(404, "PARTNER_PROFILE_NOT_FOUND", "Parceiro de origem não encontrado.")
        if not _is_internal(context):
            if context.role not in PARTNER_ROLES or payload.source_partner_tenant_id != context.tenant_id:
                raise ApiError(403, "PARTNER_ATTRIBUTION_NOT_ALLOWED", "Atribuição de parceiro não autorizada.")
    owner_tenant_id = profile.tenant_id
    credit_request = CreditRequest(
        owner_tenant_id=owner_tenant_id,
        borrower_profile_id=profile.borrower_profile_id,
        source_partner_tenant_id=payload.source_partner_tenant_id,
        title=payload.title,
        credit_type=payload.credit_type,
        requested_amount=payload.requested_amount,
        currency=payload.currency.upper(),
        term_months=payload.term_months,
        grace_months=payload.grace_months,
        collateral_types=payload.collateral_types,
        sectors=payload.sectors,
        regions=payload.regions,
        project_stage=payload.project_stage,
        purpose=payload.purpose,
        consent_status=payload.consent_status,
        status=payload.status,
        created_by=context.user_id,
    )
    db.add(credit_request)
    db.flush()
    _audit(db, request, context, "CREDIT_REQUEST_CREATED", "CREDIT_REQUEST", credit_request.credit_request_id)
    db.commit()
    db.refresh(credit_request)
    return credit_request


@router.get("/credit-requests", response_model=list[CreditRequestRead])
def list_credit_requests(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[CreditRequest]:
    query = select(CreditRequest)
    if not _is_internal(context):
        query = query.where(
            (CreditRequest.owner_tenant_id == context.tenant_id)
            | (CreditRequest.source_partner_tenant_id == context.tenant_id)
        )
    return list(db.scalars(query.order_by(CreditRequest.created_at.desc())).all())


@router.post("/credit-requests/{credit_request_id}/documents", response_model=CreditRequestDocumentRead, status_code=201)
def upload_credit_request_document(
    credit_request_id: str,
    payload: CreditRequestDocumentCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CreditRequestDocument:
    _require_role(context, BORROWER_ROLES | PARTNER_ROLES | INTERNAL_ROLES)
    credit_request = db.scalar(select(CreditRequest).where(CreditRequest.credit_request_id == credit_request_id))
    if credit_request is None:
        raise ApiError(404, "CREDIT_REQUEST_NOT_FOUND", "Demanda de crédito não encontrada.")
    if not _is_internal(context) and context.tenant_id not in {
        credit_request.owner_tenant_id,
        credit_request.source_partner_tenant_id,
    }:
        raise ApiError(403, "CREDIT_REQUEST_NOT_ALLOWED", "Demanda fora do escopo do tenant.")
    document = CreditRequestDocument(
        credit_request_id=credit_request.credit_request_id,
        owner_tenant_id=credit_request.owner_tenant_id,
        filename=payload.filename,
        document_type=payload.document_type,
        storage_key=f"mock/credit-requests/{credit_request.credit_request_id}/{payload.filename}",
        checksum_sha256=payload.checksum_sha256,
        uploaded_by=context.user_id,
    )
    db.add(document)
    db.flush()
    _audit(db, request, context, "CREDIT_REQUEST_DOCUMENT_UPLOADED", "CREDIT_REQUEST_DOCUMENT", document.credit_request_document_id)
    db.commit()
    db.refresh(document)
    return document


@router.get("/credit-requests/{credit_request_id}/documents", response_model=list[CreditRequestDocumentRead])
def list_credit_request_documents(
    credit_request_id: str,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[CreditRequestDocument]:
    credit_request = db.scalar(select(CreditRequest).where(CreditRequest.credit_request_id == credit_request_id))
    if credit_request is None:
        raise ApiError(404, "CREDIT_REQUEST_NOT_FOUND", "Demanda de crédito não encontrada.")
    if not _is_internal(context) and context.tenant_id not in {
        credit_request.owner_tenant_id,
        credit_request.source_partner_tenant_id,
    }:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Recurso não encontrado.")
    return list(
        db.scalars(
            select(CreditRequestDocument)
            .where(CreditRequestDocument.credit_request_id == credit_request_id)
            .order_by(CreditRequestDocument.uploaded_at.desc())
        ).all()
    )


@router.post("/credit-requests/{credit_request_id}/matching", response_model=list[MatchRead], status_code=201)
def run_matching(
    credit_request_id: str,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[Match]:
    _require_role(context, INTERNAL_ROLES)
    credit_request = db.scalar(select(CreditRequest).where(CreditRequest.credit_request_id == credit_request_id))
    if credit_request is None:
        raise ApiError(404, "CREDIT_REQUEST_NOT_FOUND", "Demanda de crédito não encontrada.")
    if credit_request.consent_status != "GRANTED":
        raise ApiError(409, "CONSENT_REQUIRED", "Consentimento é necessário antes do matching.")
    products = list(
        db.scalars(select(FundingProduct).where(FundingProduct.status == "ACTIVE")).all()
    )
    results: list[Match] = []
    for product in products:
        evaluation = evaluate_match(credit_request, product)
        existing = db.scalar(
            select(Match).where(
                Match.credit_request_id == credit_request.credit_request_id,
                Match.funding_product_id == product.funding_product_id,
            )
        )
        if existing is None:
            existing = Match(
                credit_request_id=credit_request.credit_request_id,
                funding_product_id=product.funding_product_id,
                borrower_tenant_id=credit_request.owner_tenant_id,
                funder_tenant_id=product.provider_tenant_id,
                score=evaluation.score,
                eligible=evaluation.eligible,
                reasons=evaluation.reasons,
                gaps=evaluation.gaps,
                status="SUGGESTED",
                assigned_agent_id=context.user_id,
                created_by=context.user_id,
            )
            db.add(existing)
            db.flush()
            db.add(
                MatchEvent(
                    match_id=existing.match_id,
                    status="SUGGESTED",
                    reason="Match calculado por regras determinísticas R5.",
                    actor_id=context.user_id,
                    visibility="INTERNAL",
                )
            )
        else:
            existing.score = evaluation.score
            existing.eligible = evaluation.eligible
            existing.reasons = evaluation.reasons
            existing.gaps = evaluation.gaps
            existing.assigned_agent_id = context.user_id
        results.append(existing)
    credit_request.status = "MATCHING"
    credit_request.version += 1
    _audit(db, request, context, "CREDIT_REQUEST_MATCHED", "CREDIT_REQUEST", credit_request.credit_request_id)
    db.commit()
    for result in results:
        db.refresh(result)
    return results


@router.get("/matches", response_model=list[MatchRead])
def list_matches(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[Match]:
    query = select(Match)
    if _is_internal(context):
        pass
    elif context.role in FUNDER_ROLES:
        query = query.where(Match.funder_tenant_id == context.tenant_id)
    else:
        query = query.where(Match.borrower_tenant_id == context.tenant_id)
    return list(db.scalars(query.order_by(Match.score.desc(), Match.created_at.desc())).all())


@router.post("/matches/{match_id}/status", response_model=MatchRead)
def update_match_status(
    match_id: str,
    payload: MatchStatusUpdate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> Match:
    match = db.scalar(select(Match).where(Match.match_id == match_id))
    if match is None:
        raise ApiError(404, "MATCH_NOT_FOUND", "Match não encontrado.")
    if not _is_internal(context) and context.tenant_id != match.funder_tenant_id:
        raise ApiError(403, "MATCH_NOT_ALLOWED", "Acesso não autorizado.")
    if not _is_internal(context) and payload.status not in {"INTERESTED", "DECLINED"}:
        raise ApiError(403, "MATCH_STATUS_NOT_ALLOWED", "Status não permitido para este papel.")
    if _is_internal(context) and payload.status == "APPROVED_TO_CONTACT":
        from app.models import RiskAssessment

        latest_assessment = db.scalar(
            select(RiskAssessment)
            .where(RiskAssessment.credit_request_id == match.credit_request_id)
            .order_by(RiskAssessment.created_at.desc())
        )
        if latest_assessment is None:
            raise ApiError(409, "RISK_ASSESSMENT_REQUIRED", "Use o painel de governança para registrar uma avaliação antes de liberar o contato.")
        if latest_assessment.hard_flags or latest_assessment.decision in {"BLOCKED", "INFORMATION_REQUIRED"} or latest_assessment.human_status != "APPROVED":
            raise ApiError(409, "HUMAN_REVIEW_REQUIRED", "A liberação exige decisão humana registrada no painel de governança.")
    match.status = payload.status
    if _is_internal(context):
        match.assigned_agent_id = context.user_id
    db.add(
        MatchEvent(
            match_id=match.match_id,
            status=payload.status,
            reason=payload.reason,
            actor_id=context.user_id,
            visibility=payload.visibility,
        )
    )
    _audit(db, request, context, "MATCH_STATUS_UPDATED", "MATCH", match.match_id)
    db.commit()
    db.refresh(match)
    return match


@router.post("/commission-events", response_model=CommissionEventRead, status_code=201)
def create_commission_event(
    payload: CommissionEventCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CommissionEvent:
    _require_role(context, INTERNAL_ROLES)
    match = db.scalar(select(Match).where(Match.match_id == payload.match_id))
    if match is None:
        raise ApiError(404, "MATCH_NOT_FOUND", "Match não encontrado.")
    beneficiary = db.scalar(
        select(Tenant).where(Tenant.tenant_id == payload.beneficiary_tenant_id, Tenant.status == "ACTIVE")
    )
    if beneficiary is None:
        raise ApiError(404, "BENEFICIARY_TENANT_NOT_FOUND", "Tenant beneficiário não encontrado.")
    estimated_amount = (payload.base_amount * Decimal(payload.rate_bps)) / Decimal(10000)
    event = CommissionEvent(
        match_id=match.match_id,
        beneficiary_tenant_id=payload.beneficiary_tenant_id,
        event_type=payload.event_type,
        base_amount=payload.base_amount,
        rate_bps=payload.rate_bps,
        estimated_amount=estimated_amount,
        created_by=context.user_id,
    )
    db.add(event)
    db.flush()
    _audit(db, request, context, "COMMISSION_EVENT_CREATED", "COMMISSION_EVENT", event.commission_event_id)
    db.commit()
    db.refresh(event)
    return event

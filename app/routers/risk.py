from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.errors import ApiError
from app.models import CreditRequest, Match, MatchGovernanceReview, RiskAssessment
from app.risk_engine import POLICY_VERSION, evaluate_risk
from app.schemas import (
    GovernanceQueueItemRead,
    GovernanceReviewCreate,
    GovernanceReviewRead,
    RiskAssessmentRead,
    RiskRuleRead,
    RiskSimulationInput,
)
from app.security import SecurityContext, require_security_context

router = APIRouter(prefix="/api/v1/risk", tags=["risk-governance"])
INTERNAL_ROLES = {"ANALYST", "PLATFORM_ADMIN", "INTERNAL_AGENT", "CREDIT_ANALYST"}
PARTICIPANT_ROLES = INTERNAL_ROLES | {"ORIGINATOR_ADMIN", "CLIENT_ADMIN", "BORROWER_ADMIN", "BORROWER_EDITOR", "FUNDER_ADMIN", "FUNDER_EDITOR", "INVESTOR_ANALYST", "PARTNER_ADMIN", "PARTNER_EDITOR"}


def _require_internal(context: SecurityContext) -> None:
    if context.role not in INTERNAL_ROLES:
        raise ApiError(403, "INTERNAL_ONLY", "A avaliação de risco e a governança são operações internas.")


def _audit(db: Session, request: Request, context: SecurityContext, action: str, resource_type: str, resource_id: str, detail: dict | None = None) -> None:
    record_audit(
        db,
        context=context,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
        detail=detail or {},
    )


def _assessment_read(assessment: RiskAssessment) -> RiskAssessmentRead:
    return RiskAssessmentRead(
        assessment_id=assessment.assessment_id,
        credit_request_id=assessment.credit_request_id,
        policy_version=assessment.policy_version,
        decision=assessment.decision,
        risk_band=assessment.risk_band,
        score=assessment.score,
        recommendation=assessment.recommendation,
        rule_results=[RiskRuleRead(**item) for item in assessment.rule_results],
        evidence=assessment.evidence,
        missing_data=assessment.missing_data,
        hard_flags=assessment.hard_flags,
        soft_flags=assessment.soft_flags,
        human_status=assessment.human_status,
        created_by=assessment.created_by,
        created_at=assessment.created_at,
    )


def _review_read(review: MatchGovernanceReview) -> GovernanceReviewRead:
    return GovernanceReviewRead(
        review_id=review.review_id,
        match_id=review.match_id,
        assessment_id=review.assessment_id,
        decision=review.decision,
        reason=review.reason,
        actor_id=review.actor_id,
        created_at=review.created_at,
    )


@router.post("/simulate", response_model=RiskAssessmentRead)
def simulate_risk(
    payload: RiskSimulationInput,
    context: SecurityContext = Depends(require_security_context),
) -> RiskAssessmentRead:
    if context.role not in PARTICIPANT_ROLES:
        raise ApiError(403, "ROLE_NOT_ALLOWED", "Papel não autorizado para simulação.")
    evaluation = evaluate_risk(payload)
    return RiskAssessmentRead(
        assessment_id="SIMULATION",
        credit_request_id=payload.credit_request_id,
        policy_version=POLICY_VERSION,
        decision=evaluation.decision,
        risk_band=evaluation.risk_band,
        score=evaluation.score,
        recommendation=evaluation.recommendation,
        rule_results=[RiskRuleRead(**rule.__dict__) for rule in evaluation.rule_results],
        evidence=evaluation.evidence,
        missing_data=evaluation.missing_data,
        hard_flags=evaluation.hard_flags,
        soft_flags=evaluation.soft_flags,
        human_status="NOT_PERSISTED",
        created_by=context.user_id,
        created_at=datetime.now(timezone.utc),
    )


@router.post("/credit-requests/{credit_request_id}/assessments", response_model=RiskAssessmentRead, status_code=201)
def create_risk_assessment(
    credit_request_id: str,
    payload: RiskSimulationInput,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> RiskAssessmentRead:
    _require_internal(context)
    credit_request = db.scalar(select(CreditRequest).where(CreditRequest.credit_request_id == credit_request_id))
    if credit_request is None:
        raise ApiError(404, "CREDIT_REQUEST_NOT_FOUND", "Demanda de crédito não encontrada.")
    if payload.credit_request_id and payload.credit_request_id != credit_request_id:
        raise ApiError(422, "RISK_REQUEST_MISMATCH", "A demanda do payload não corresponde ao recurso avaliado.")
    payload.credit_request_id = credit_request_id
    evaluation = evaluate_risk(payload)
    assessment = RiskAssessment(
        credit_request_id=credit_request_id,
        policy_version=POLICY_VERSION,
        decision=evaluation.decision,
        risk_band=evaluation.risk_band,
        score=evaluation.score,
        recommendation=evaluation.recommendation,
        rule_results=[rule.__dict__ for rule in evaluation.rule_results],
        evidence=evaluation.evidence,
        missing_data=evaluation.missing_data,
        hard_flags=evaluation.hard_flags,
        soft_flags=evaluation.soft_flags,
        human_status="PENDING",
        created_by=context.user_id,
    )
    db.add(assessment)
    db.flush()
    _audit(db, request, context, "RISK_ASSESSMENT_CREATED", "RISK_ASSESSMENT", assessment.assessment_id, {"decision": assessment.decision, "risk_band": assessment.risk_band, "score": assessment.score, "policy_version": POLICY_VERSION})
    db.commit()
    db.refresh(assessment)
    return _assessment_read(assessment)


@router.get("/credit-requests/{credit_request_id}/assessments", response_model=list[RiskAssessmentRead])
def list_risk_assessments(
    credit_request_id: str,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[RiskAssessmentRead]:
    _require_internal(context)
    assessments = db.scalars(
        select(RiskAssessment)
        .where(RiskAssessment.credit_request_id == credit_request_id)
        .order_by(RiskAssessment.created_at.desc())
    ).all()
    return [_assessment_read(item) for item in assessments]


@router.get("/governance-queue", response_model=list[GovernanceQueueItemRead])
def governance_queue(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[GovernanceQueueItemRead]:
    _require_internal(context)
    matches = db.scalars(select(Match).order_by(Match.score.desc(), Match.created_at.desc())).all()
    output: list[GovernanceQueueItemRead] = []
    for match in matches:
        assessment = db.scalar(
            select(RiskAssessment)
            .where(RiskAssessment.credit_request_id == match.credit_request_id)
            .order_by(RiskAssessment.created_at.desc())
        )
        review = db.scalar(
            select(MatchGovernanceReview)
            .where(MatchGovernanceReview.match_id == match.match_id)
            .order_by(MatchGovernanceReview.created_at.desc())
        )
        output.append(
            GovernanceQueueItemRead(
                match_id=match.match_id,
                credit_request_id=match.credit_request_id,
                funding_product_id=match.funding_product_id,
                score=match.score,
                eligible=match.eligible,
                match_status=match.status,
                risk_assessment=_assessment_read(assessment) if assessment else None,
                latest_review=_review_read(review) if review else None,
                requires_human_decision=review is None or review.decision == "REQUEST_INFORMATION",
            )
        )
    return output


@router.post("/matches/{match_id}/governance-reviews", response_model=GovernanceReviewRead, status_code=201)
def create_governance_review(
    match_id: str,
    payload: GovernanceReviewCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> GovernanceReviewRead:
    _require_internal(context)
    match = db.scalar(select(Match).where(Match.match_id == match_id))
    if match is None:
        raise ApiError(404, "MATCH_NOT_FOUND", "Match não encontrado.")
    if payload.decision == "APPROVE_CONTACT":
        latest_review = db.scalar(
            select(MatchGovernanceReview)
            .where(MatchGovernanceReview.match_id == match_id)
            .order_by(MatchGovernanceReview.created_at.desc())
        )
        reviewable_states = {"SUGGESTED", "AGENT_REVIEW", "INTERESTED", "DILIGENCE", "NEGOTIATION"}
        if match.status not in reviewable_states and not (match.status == "APPROVED_TO_CONTACT" and latest_review is None):
            raise ApiError(409, "MATCH_STATE_NOT_REVIEWABLE", "O match não está em um estado revisável.")
        latest_assessment = None
        if payload.assessment_id:
            latest_assessment = db.scalar(select(RiskAssessment).where(RiskAssessment.assessment_id == payload.assessment_id))
        if latest_assessment is None:
            latest_assessment = db.scalar(
                select(RiskAssessment)
                .where(RiskAssessment.credit_request_id == match.credit_request_id)
                .order_by(RiskAssessment.created_at.desc())
            )
        if latest_assessment is None:
            raise ApiError(409, "RISK_ASSESSMENT_REQUIRED", "Execute uma avaliação de risco antes de liberar o contato.")
        if latest_assessment.hard_flags or latest_assessment.decision in {"BLOCKED", "INFORMATION_REQUIRED"}:
            raise ApiError(409, "RISK_REVIEW_NOT_CLEAR", "A avaliação de risco ainda possui bloqueios ou informações pendentes.")
        payload.assessment_id = latest_assessment.assessment_id
        latest_assessment.human_status = "APPROVED"
        match.status = "APPROVED_TO_CONTACT"
    elif payload.decision == "REQUEST_INFORMATION":
        match.status = "AGENT_REVIEW"
    elif payload.decision == "BLOCK":
        match.status = "BLOCKED"
    elif payload.decision == "REJECT":
        match.status = "DECLINED"
    review = MatchGovernanceReview(
        match_id=match_id,
        assessment_id=payload.assessment_id,
        decision=payload.decision,
        reason=payload.reason,
        actor_id=context.user_id,
        visibility=payload.visibility,
    )
    db.add(review)
    db.flush()
    _audit(db, request, context, "MATCH_GOVERNANCE_REVIEWED", "MATCH", match_id, {"decision": payload.decision, "assessment_id": payload.assessment_id, "reason": payload.reason})
    db.commit()
    db.refresh(review)
    return _review_read(review)

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.contracts.post_closing import (
    CommissionEstimateRequest,
    CommissionLedgerRead,
    CommissionTransitionRequest,
    OutboxMetricsRead,
    ReconciliationOutboxRead,
    ReconciliationReviewRead,
    ReconciliationResultRead,
    ReviewClaimRequest,
    ReviewResolveRequest,
    SettlementEventRequest,
)
from app.db import get_db
from app.errors import ApiError
from app.models import (
    CommissionLedgerEntryRecord,
    ReconciliationOutboxRecord,
    ReconciliationReviewRecord,
)
from app.outbox_observability import OutboxObservabilityService
from app.persistent_reconciliation import PersistentReconciliationService
from app.post_closing import CommissionStatus
from app.reconciliation_engine import ReconciliationResult, SettlementEvent
from app.security import SecurityContext, require_security_context


router = APIRouter(prefix="/api/v1/reconciliation/persistent", tags=["persistent-reconciliation"])
INTERNAL_ROLES = {"ANALYST", "PLATFORM_ADMIN", "INTERNAL_AGENT", "CREDIT_ANALYST"}
service = PersistentReconciliationService()
outbox_observability = OutboxObservabilityService()


def _require_internal(context: SecurityContext) -> None:
    if context.role not in INTERNAL_ROLES:
        raise ApiError(403, "INTERNAL_ONLY", "A conciliação persistente é uma operação interna.")


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


def _commission_read(row: CommissionLedgerEntryRecord) -> CommissionLedgerRead:
    return CommissionLedgerRead(
        commission_id=row.commission_id,
        match_id=row.match_id,
        beneficiary_tenant_id=row.beneficiary_tenant_id,
        contract_id=row.contract_id,
        trigger_event=row.trigger_event,
        base_amount=Decimal(str(row.base_amount)),
        rate_bps=row.rate_bps,
        estimated_amount=Decimal(str(row.estimated_amount)),
        status=row.status,
        currency=row.currency,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata={str(k): str(v) for k, v in (row.metadata_json or {}).items()},
    )


def _result_read(result: ReconciliationResult) -> ReconciliationResultRead:
    return ReconciliationResultRead(
        reconciliation_id=result.reconciliation_id,
        external_event_id=result.external_event_id,
        decision=result.decision.value,
        reason=result.reason.value,
        commission_id=result.commission_id,
        candidate_commission_ids=list(result.candidate_commission_ids),
        amount_variance=result.amount_variance,
        policy_version=result.policy_version,
        reconciled_at=result.reconciled_at,
        detail=result.detail,
    )


def _review_read(row: ReconciliationReviewRecord) -> ReconciliationReviewRead:
    return ReconciliationReviewRead(
        review_id=row.review_id,
        inbox_id=row.inbox_id,
        link_id=row.link_id,
        status=row.status,
        reason=row.reason,
        expected_amount=Decimal(str(row.expected_amount)) if row.expected_amount is not None else None,
        received_amount=Decimal(str(row.received_amount)),
        amount_variance=Decimal(str(row.amount_variance)) if row.amount_variance is not None else None,
        currency=row.currency,
        assigned_to=row.assigned_to,
        decision=row.decision,
        notes=row.notes,
        due_at=row.due_at,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _outbox_read(row: ReconciliationOutboxRecord) -> ReconciliationOutboxRead:
    return ReconciliationOutboxRead(
        outbox_id=row.outbox_id,
        event_key=row.event_key,
        event_type=row.event_type,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        payload=row.payload,
        status=row.status,
        attempt_count=row.attempt_count,
        available_at=row.available_at,
        created_at=row.created_at,
        published_at=row.published_at,
        claimed_at=row.claimed_at,
        lease_until=row.lease_until,
        last_attempt_at=row.last_attempt_at,
        failed_at=row.failed_at,
        dead_lettered_at=row.dead_lettered_at,
        last_error=row.last_error,
    )


def _event(payload: SettlementEventRequest) -> SettlementEvent:
    return SettlementEvent(
        external_event_id=payload.external_event_id,
        beneficiary_tenant_id=payload.beneficiary_tenant_id,
        amount=payload.amount,
        currency=payload.currency.upper(),
        settled_at=payload.settled_at,
        contract_id=payload.contract_id,
        match_id=payload.match_id,
        invoice_reference=payload.invoice_reference,
        account_fingerprint=payload.account_fingerprint,
        source=payload.source,
        metadata=payload.metadata,
    )


@router.post("/commissions", response_model=CommissionLedgerRead, status_code=201)
def register_commission(
    payload: CommissionEstimateRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CommissionLedgerRead:
    _require_internal(context)
    try:
        row = service.register_commission(
            db,
            match_id=payload.match_id,
            beneficiary_tenant_id=payload.beneficiary_tenant_id,
            trigger_event=payload.trigger_event,
            base_amount=payload.base_amount,
            rate_bps=payload.rate_bps,
            currency=payload.currency,
            contract_id=payload.contract_id,
        )
    except Exception as exc:
        db.rollback()
        raise ApiError(422, "COMMISSION_REGISTER_FAILED", str(exc)) from exc
    _audit(db, request, context, "PERSISTENT_COMMISSION_REGISTERED", "COMMISSION_LEDGER", row.commission_id)
    db.commit()
    db.refresh(row)
    return _commission_read(row)


@router.post("/commissions/{commission_id}/transition", response_model=CommissionLedgerRead)
def transition_commission(
    commission_id: str,
    payload: CommissionTransitionRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CommissionLedgerRead:
    _require_internal(context)
    try:
        row = service.transition_commission(
            db,
            commission_id=commission_id,
            status=CommissionStatus(payload.status),
            contract_id=payload.contract_id,
            metadata=payload.metadata,
        )
    except KeyError as exc:
        raise ApiError(404, "COMMISSION_NOT_FOUND", "Comissão persistente não encontrada.") from exc
    except (ValueError, TypeError) as exc:
        raise ApiError(409, "COMMISSION_TRANSITION_INVALID", str(exc)) from exc
    _audit(db, request, context, "PERSISTENT_COMMISSION_TRANSITIONED", "COMMISSION_LEDGER", commission_id, {"status": payload.status})
    db.commit()
    db.refresh(row)
    return _commission_read(row)


@router.post("/settlements", response_model=ReconciliationResultRead)
def reconcile_settlement(
    payload: SettlementEventRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ReconciliationResultRead:
    _require_internal(context)
    try:
        result = service.reconcile(db, _event(payload))
    except Exception:
        db.rollback()
        raise
    _audit(db, request, context, "PERSISTENT_SETTLEMENT_RECONCILED", "RECONCILIATION", result.reconciliation_id, {"decision": result.decision.value, "reason": result.reason.value, "external_event_id": result.external_event_id})
    db.commit()
    return _result_read(result)


@router.get("/reviews", response_model=list[ReconciliationReviewRead])
def list_reviews(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[ReconciliationReviewRead]:
    _require_internal(context)
    rows = db.scalars(
        select(ReconciliationReviewRecord)
        .where(ReconciliationReviewRecord.status.in_({"OPEN", "CLAIMED", "WAITING_INFORMATION"}))
        .order_by(ReconciliationReviewRecord.due_at.asc(), ReconciliationReviewRecord.created_at.asc())
    ).all()
    return [_review_read(row) for row in rows]


@router.post("/reviews/claim", response_model=list[ReconciliationReviewRead])
def claim_reviews(
    payload: ReviewClaimRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[ReconciliationReviewRead]:
    _require_internal(context)
    rows = service.claim_reviews(db, actor_id=payload.assigned_to or context.user_id)
    _audit(db, request, context, "RECONCILIATION_REVIEWS_CLAIMED", "RECONCILIATION_REVIEW_QUEUE", request.state.request_id, {"count": len(rows)})
    db.commit()
    return [_review_read(row) for row in rows]


@router.post("/reviews/{review_id}/resolve", response_model=ReconciliationReviewRead)
def resolve_review(
    review_id: str,
    payload: ReviewResolveRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ReconciliationReviewRead:
    _require_internal(context)
    try:
        row = service.resolve_review(
            db,
            review_id=review_id,
            actor_id=context.user_id,
            decision=payload.decision,
            notes=payload.notes,
        )
    except KeyError as exc:
        raise ApiError(404, "REVIEW_NOT_FOUND", "Exceção de conciliação não encontrada.") from exc
    except PermissionError as exc:
        raise ApiError(403, "REVIEW_ASSIGNED_TO_OTHER", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(409, "REVIEW_RESOLUTION_INVALID", str(exc)) from exc
    _audit(db, request, context, "RECONCILIATION_REVIEW_RESOLVED", "RECONCILIATION_REVIEW", review_id, {"decision": payload.decision})
    db.commit()
    db.refresh(row)
    return _review_read(row)


@router.post("/outbox/claim", response_model=list[ReconciliationOutboxRead])
def claim_outbox(
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[ReconciliationOutboxRead]:
    _require_internal(context)
    rows = service.claim_outbox(db)
    _audit(db, request, context, "RECONCILIATION_OUTBOX_CLAIMED", "RECONCILIATION_OUTBOX", request.state.request_id, {"count": len(rows)})
    db.commit()
    return [_outbox_read(row) for row in rows]


@router.get("/outbox/metrics", response_model=OutboxMetricsRead)
def outbox_metrics(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> OutboxMetricsRead:
    _require_internal(context)
    return OutboxMetricsRead(**outbox_observability.snapshot(db))


@router.post("/outbox/{outbox_id}/ack", response_model=ReconciliationOutboxRead)
def ack_outbox(
    outbox_id: str,
    published: bool,
    request: Request,
    error: str | None = None,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ReconciliationOutboxRead:
    _require_internal(context)
    try:
        row = service.mark_outbox(db, outbox_id=outbox_id, published=published, error=error)
    except KeyError as exc:
        raise ApiError(404, "OUTBOX_NOT_FOUND", "Evento outbox não encontrado.") from exc
    _audit(db, request, context, "RECONCILIATION_OUTBOX_ACKED", "RECONCILIATION_OUTBOX", outbox_id, {"published": published})
    db.commit()
    db.refresh(row)
    return _outbox_read(row)

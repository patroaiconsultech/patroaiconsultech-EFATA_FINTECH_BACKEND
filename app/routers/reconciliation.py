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
    ReconciliationBatchRead,
    ReconciliationResultRead,
    SettlementEventRequest,
)
from app.db import get_db
from app.errors import ApiError
from app.models import Match, Tenant
from app.post_closing import CommissionLedgerEntry, CommissionStatus, InvalidTransition
from app.reconciliation_engine import (
    CommissionReconciliationEngine,
    ReconciliationDecision,
    ReconciliationResult,
    SettlementEvent,
)
from app.security import SecurityContext, require_security_context


router = APIRouter(prefix="/api/v1/reconciliation", tags=["commission-reconciliation"])
INTERNAL_ROLES = {"ANALYST", "PLATFORM_ADMIN", "INTERNAL_AGENT", "CREDIT_ANALYST"}

# Prototype scope: process-local engine. Production must replace this registry
# with PostgreSQL tables, unique constraints and a durable inbox/outbox.
engine = CommissionReconciliationEngine()


def _require_internal(context: SecurityContext) -> None:
    if context.role not in INTERNAL_ROLES:
        raise ApiError(403, "INTERNAL_ONLY", "A conciliação de comissões é uma operação interna.")


def _audit(
    db: Session,
    request: Request,
    context: SecurityContext,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict | None = None,
) -> None:
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


def _commission_read(entry: CommissionLedgerEntry) -> CommissionLedgerRead:
    return CommissionLedgerRead(
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
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        metadata=entry.metadata,
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


def _validate_entities(payload: CommissionEstimateRequest, db: Session) -> None:
    match = db.scalar(select(Match).where(Match.match_id == payload.match_id))
    if match is None:
        raise ApiError(404, "MATCH_NOT_FOUND", "Match não encontrado.")
    beneficiary = db.scalar(
        select(Tenant).where(Tenant.tenant_id == payload.beneficiary_tenant_id, Tenant.status == "ACTIVE")
    )
    if beneficiary is None:
        raise ApiError(404, "BENEFICIARY_TENANT_NOT_FOUND", "Tenant beneficiário não encontrado.")


@router.post("/commissions", response_model=CommissionLedgerRead, status_code=201)
def create_commission(
    payload: CommissionEstimateRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> CommissionLedgerRead:
    _require_internal(context)
    _validate_entities(payload, db)
    entry = CommissionLedgerEntry.estimate(
        match_id=payload.match_id,
        beneficiary_tenant_id=payload.beneficiary_tenant_id,
        trigger_event=payload.trigger_event,
        base_amount=payload.base_amount,
        rate_bps=payload.rate_bps,
        currency=payload.currency.upper(),
        contract_id=payload.contract_id,
    )
    engine.add_commission(entry)
    _audit(
        db,
        request,
        context,
        "COMMISSION_RECONCILIATION_ENTRY_CREATED",
        "COMMISSION_LEDGER",
        entry.commission_id,
        {"match_id": entry.match_id, "estimated_amount": str(entry.estimated_amount), "policy_version": engine.policy_version},
    )
    db.commit()
    return _commission_read(entry)


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
        status = CommissionStatus(payload.status)
        entry = engine.transition_commission(
            commission_id,
            status,
            contract_id=payload.contract_id,
            metadata=payload.metadata,
        )
    except KeyError as exc:
        raise ApiError(404, "COMMISSION_NOT_FOUND", "Comissão não encontrada no registry do protótipo.") from exc
    except (ValueError, InvalidTransition) as exc:
        raise ApiError(409, "COMMISSION_TRANSITION_INVALID", str(exc)) from exc
    _audit(db, request, context, "COMMISSION_LEDGER_TRANSITIONED", "COMMISSION_LEDGER", commission_id, {"status": status.value})
    db.commit()
    return _commission_read(entry)


@router.get("/commissions/{commission_id}", response_model=CommissionLedgerRead)
def read_commission(
    commission_id: str,
    context: SecurityContext = Depends(require_security_context),
) -> CommissionLedgerRead:
    _require_internal(context)
    try:
        return _commission_read(engine.commission(commission_id))
    except KeyError as exc:
        raise ApiError(404, "COMMISSION_NOT_FOUND", "Comissão não encontrada no registry do protótipo.") from exc


@router.post("/settlements", response_model=ReconciliationResultRead)
def ingest_settlement(
    payload: SettlementEventRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ReconciliationResultRead:
    _require_internal(context)
    event = SettlementEvent(
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
    result = engine.ingest_settlement(event)
    _audit(
        db,
        request,
        context,
        "COMMISSION_SETTLEMENT_RECONCILED",
        "RECONCILIATION",
        result.reconciliation_id,
        {"external_event_id": result.external_event_id, "decision": result.decision.value, "reason": result.reason.value, "commission_id": result.commission_id},
    )
    db.commit()
    return _result_read(result)


@router.post("/settlements/batch", response_model=ReconciliationBatchRead)
def ingest_settlement_batch(
    payload: list[SettlementEventRequest],
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ReconciliationBatchRead:
    _require_internal(context)
    results: list[ReconciliationResultRead] = []
    for item in payload:
        event = SettlementEvent(
            external_event_id=item.external_event_id,
            beneficiary_tenant_id=item.beneficiary_tenant_id,
            amount=item.amount,
            currency=item.currency.upper(),
            settled_at=item.settled_at,
            contract_id=item.contract_id,
            match_id=item.match_id,
            invoice_reference=item.invoice_reference,
            account_fingerprint=item.account_fingerprint,
            source=item.source,
            metadata=item.metadata,
        )
        results.append(_result_read(engine.ingest_settlement(event)))
    _audit(db, request, context, "COMMISSION_SETTLEMENT_BATCH_RECONCILED", "RECONCILIATION_BATCH", request.state.request_id, {"processed": len(results)})
    db.commit()
    return ReconciliationBatchRead(
        processed=len(results),
        auto_reconciled=sum(item.decision == ReconciliationDecision.AUTO_RECONCILED.value for item in results),
        review_required=sum(item.decision == ReconciliationDecision.REVIEW_REQUIRED.value for item in results),
        unmatched=sum(item.decision == ReconciliationDecision.UNMATCHED.value for item in results),
        duplicates=sum(item.decision == ReconciliationDecision.DUPLICATE.value for item in results),
        results=results,
    )


@router.get("/review-queue", response_model=list[ReconciliationResultRead])
def review_queue(
    context: SecurityContext = Depends(require_security_context),
) -> list[ReconciliationResultRead]:
    _require_internal(context)
    return [_result_read(result) for result in engine.pending_review()]

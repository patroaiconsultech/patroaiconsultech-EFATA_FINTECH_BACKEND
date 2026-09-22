"""Automatic reconciliation prototype for commission flow J.

The engine reconciles settlement events against commission-ledger entries. It
is deliberately deterministic and persistence-agnostic: production should
back the same invariants with unique database constraints, a durable inbox,
and an append-only audit/event table.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from typing import Iterable
from uuid import uuid4

from app.post_closing import CommissionLedgerEntry, CommissionStatus, InvalidTransition


class ReconciliationDecision(StrEnum):
    AUTO_RECONCILED = "AUTO_RECONCILED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNMATCHED = "UNMATCHED"
    DUPLICATE = "DUPLICATE"


class ReconciliationReason(StrEnum):
    EXACT_REFERENCE_AND_AMOUNT = "EXACT_REFERENCE_AND_AMOUNT"
    AMOUNT_VARIANCE = "AMOUNT_VARIANCE"
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
    NO_CANDIDATE = "NO_CANDIDATE"
    COMMISSION_NOT_READY = "COMMISSION_NOT_READY"
    DUPLICATE_EXTERNAL_EVENT = "DUPLICATE_EXTERNAL_EVENT"


@dataclass(frozen=True, slots=True)
class SettlementEvent:
    """Normalized settlement event from a bank, ERP or payment processor."""

    external_event_id: str
    beneficiary_tenant_id: str
    amount: Decimal
    currency: str
    settled_at: datetime
    contract_id: str | None = None
    match_id: str | None = None
    invoice_reference: str | None = None
    account_fingerprint: str | None = None
    source: str = "BANK_SETTLEMENT_FEED"
    metadata: dict[str, str] | None = None

    @property
    def idempotency_key(self) -> tuple[str, str]:
        return (self.source, self.external_event_id)

    def __post_init__(self) -> None:
        if not self.external_event_id.strip():
            raise ValueError("external_event_id is required")
        if self.amount < 0:
            raise ValueError("amount cannot be negative")
        if len(self.currency) != 3:
            raise ValueError("currency must be a three-letter code")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    reconciliation_id: str
    external_event_id: str
    decision: ReconciliationDecision
    reason: ReconciliationReason
    commission_id: str | None
    candidate_commission_ids: tuple[str, ...]
    amount_variance: Decimal | None
    policy_version: str
    reconciled_at: datetime
    detail: dict[str, str]


@dataclass(frozen=True, slots=True)
class _Candidate:
    entry: CommissionLedgerEntry
    reference_match: bool
    contract_match: bool
    match_match: bool
    amount_variance: Decimal

    @property
    def exact_amount(self) -> bool:
        return self.amount_variance == Decimal("0.00")

    @property
    def ranking(self) -> tuple[int, int, int, int]:
        return (
            int(self.reference_match),
            int(self.contract_match),
            int(self.match_match),
            int(self.exact_amount),
        )


class CommissionReconciliationEngine:
    """Deterministic, idempotent J-flow reconciliation engine."""

    policy_version = "commission-reconciliation-v1"

    def __init__(self, *, amount_tolerance: Decimal = Decimal("0.01")) -> None:
        if amount_tolerance < 0:
            raise ValueError("amount_tolerance cannot be negative")
        self.amount_tolerance = amount_tolerance
        self._entries: dict[str, CommissionLedgerEntry] = {}
        self._events: dict[tuple[str, str], SettlementEvent] = {}
        self._results: dict[tuple[str, str], ReconciliationResult] = {}
        self._lock = RLock()

    def add_commission(self, entry: CommissionLedgerEntry) -> CommissionLedgerEntry:
        with self._lock:
            if entry.commission_id in self._entries:
                raise ValueError(f"commission {entry.commission_id} already exists")
            self._entries[entry.commission_id] = entry
            return entry

    def ingest_settlement(self, event: SettlementEvent) -> ReconciliationResult:
        """Ingest one normalized event exactly once and reconcile if safe."""
        with self._lock:
            existing = self._results.get(event.idempotency_key)
            if existing is not None:
                return replace(
                    existing,
                    decision=ReconciliationDecision.DUPLICATE,
                    reason=ReconciliationReason.DUPLICATE_EXTERNAL_EVENT,
                    detail={**existing.detail, "original_decision": existing.decision.value},
                )
            self._events[event.idempotency_key] = event
            candidates = self._find_candidates(event)
            result = self._decide(event, candidates)
            self._results[event.idempotency_key] = result
            return result

    def _find_candidates(self, event: SettlementEvent) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for entry in self._entries.values():
            if entry.beneficiary_tenant_id != event.beneficiary_tenant_id:
                continue
            if entry.currency.upper() != event.currency.upper():
                continue
            if entry.status in {CommissionStatus.VOIDED, CommissionStatus.RECONCILED}:
                continue
            metadata = entry.metadata
            reference_match = bool(
                event.invoice_reference
                and metadata.get("invoice_reference") == event.invoice_reference
            )
            contract_match = bool(event.contract_id and entry.contract_id == event.contract_id)
            match_match = bool(event.match_id and entry.match_id == event.match_id)
            amount_variance = abs(entry.estimated_amount - event.amount)
            if not (reference_match or contract_match or match_match):
                continue
            candidates.append(
                _Candidate(
                    entry=entry,
                    reference_match=reference_match,
                    contract_match=contract_match,
                    match_match=match_match,
                    amount_variance=amount_variance,
                )
            )
        return candidates

    def _decide(self, event: SettlementEvent, candidates: list[_Candidate]) -> ReconciliationResult:
        now = datetime.now(timezone.utc)
        if not candidates:
            return ReconciliationResult(
                reconciliation_id=f"reconciliation-{uuid4()}",
                external_event_id=event.external_event_id,
                decision=ReconciliationDecision.UNMATCHED,
                reason=ReconciliationReason.NO_CANDIDATE,
                commission_id=None,
                candidate_commission_ids=(),
                amount_variance=None,
                policy_version=self.policy_version,
                reconciled_at=now,
                detail={"source": event.source},
            )

        ordered = sorted(candidates, key=lambda candidate: candidate.ranking, reverse=True)
        best = ordered[0]
        candidate_ids = tuple(candidate.entry.commission_id for candidate in ordered)
        if len(ordered) > 1 and ordered[0].ranking == ordered[1].ranking:
            return ReconciliationResult(
                reconciliation_id=f"reconciliation-{uuid4()}",
                external_event_id=event.external_event_id,
                decision=ReconciliationDecision.REVIEW_REQUIRED,
                reason=ReconciliationReason.AMBIGUOUS_CANDIDATES,
                commission_id=None,
                candidate_commission_ids=candidate_ids,
                amount_variance=best.amount_variance,
                policy_version=self.policy_version,
                reconciled_at=now,
                detail={"source": event.source, "candidate_count": str(len(ordered))},
            )

        if not best.exact_amount and best.amount_variance > self.amount_tolerance:
            return ReconciliationResult(
                reconciliation_id=f"reconciliation-{uuid4()}",
                external_event_id=event.external_event_id,
                decision=ReconciliationDecision.REVIEW_REQUIRED,
                reason=ReconciliationReason.AMOUNT_VARIANCE,
                commission_id=best.entry.commission_id,
                candidate_commission_ids=candidate_ids,
                amount_variance=best.amount_variance,
                policy_version=self.policy_version,
                reconciled_at=now,
                detail={"source": event.source, "expected": str(best.entry.estimated_amount), "received": str(event.amount)},
            )

        if not self._is_ready_for_auto_reconcile(best, event):
            return ReconciliationResult(
                reconciliation_id=f"reconciliation-{uuid4()}",
                external_event_id=event.external_event_id,
                decision=ReconciliationDecision.REVIEW_REQUIRED,
                reason=ReconciliationReason.COMMISSION_NOT_READY,
                commission_id=best.entry.commission_id,
                candidate_commission_ids=candidate_ids,
                amount_variance=best.amount_variance,
                policy_version=self.policy_version,
                reconciled_at=now,
                detail={"source": event.source, "current_status": best.entry.status.value},
            )

        self._auto_reconcile(best.entry, event, now)
        return ReconciliationResult(
            reconciliation_id=f"reconciliation-{uuid4()}",
            external_event_id=event.external_event_id,
            decision=ReconciliationDecision.AUTO_RECONCILED,
            reason=ReconciliationReason.EXACT_REFERENCE_AND_AMOUNT,
            commission_id=best.entry.commission_id,
            candidate_commission_ids=candidate_ids,
            amount_variance=best.amount_variance,
            policy_version=self.policy_version,
            reconciled_at=now,
            detail={"source": event.source, "currency": event.currency.upper()},
        )

    def _is_ready_for_auto_reconcile(self, candidate: _Candidate, event: SettlementEvent) -> bool:
        entry = candidate.entry
        has_strong_identity = candidate.reference_match and candidate.contract_match
        has_safe_identity = candidate.contract_match and candidate.match_match
        if not (has_strong_identity or has_safe_identity):
            return False
        if candidate.amount_variance > self.amount_tolerance:
            return False
        if entry.status not in {
            CommissionStatus.ELIGIBLE,
            CommissionStatus.INVOICED,
            CommissionStatus.RECEIVED,
        }:
            return False
        return bool(event.contract_id or entry.contract_id)

    def _auto_reconcile(self, entry: CommissionLedgerEntry, event: SettlementEvent, now: datetime) -> None:
        metadata = {
            "reconciliation_id": f"reconciliation-{event.external_event_id}",
            "external_event_id": event.external_event_id,
            "settled_at": event.settled_at.isoformat(),
            "reconciliation_policy": self.policy_version,
        }
        updated = entry
        try:
            if updated.status is CommissionStatus.ELIGIBLE:
                updated = updated.transition(CommissionStatus.INVOICED, metadata=metadata)
            if updated.status is CommissionStatus.INVOICED:
                updated = updated.transition(CommissionStatus.RECEIVED, metadata=metadata)
            if updated.status is CommissionStatus.RECEIVED:
                updated = updated.transition(CommissionStatus.RECONCILED, metadata=metadata)
        except InvalidTransition as exc:
            raise InvalidTransition(f"cannot auto-reconcile {entry.commission_id}: {exc}") from exc
        self._entries[entry.commission_id] = updated

    def commission(self, commission_id: str) -> CommissionLedgerEntry:
        with self._lock:
            return self._entries[commission_id]

    def transition_commission(
        self,
        commission_id: str,
        status: CommissionStatus,
        *,
        contract_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> CommissionLedgerEntry:
        with self._lock:
            entry = self._entries[commission_id]
            updated = entry.transition(status, contract_id=contract_id, metadata=metadata)
            self._entries[commission_id] = updated
            return updated

    def result(self, external_event_id: str, *, source: str = "BANK_SETTLEMENT_FEED") -> ReconciliationResult:
        with self._lock:
            return self._results[(source, external_event_id)]

    def results(self) -> list[ReconciliationResult]:
        with self._lock:
            return list(self._results.values())

    def pending_review(self) -> list[ReconciliationResult]:
        with self._lock:
            return [
                result
                for result in self._results.values()
                if result.decision is ReconciliationDecision.REVIEW_REQUIRED
            ]

"""Domain prototype for Efatà post-closing flows J and K.

The classes are intentionally persistence-agnostic. They model the API and
state transitions that should later be backed by PostgreSQL tables and an
append-only event log.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from threading import RLock
from typing import Iterable
from uuid import uuid4


class CommissionStatus(StrEnum):
    ESTIMATE_ONLY = "ESTIMATE_ONLY"
    CONTRACT_PENDING = "CONTRACT_PENDING"
    TRIGGER_PENDING = "TRIGGER_PENDING"
    ELIGIBLE = "ELIGIBLE"
    INVOICED = "INVOICED"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class MonitoringStatus(StrEnum):
    OPEN = "OPEN"
    DUE = "DUE"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"
    ESCALATED = "ESCALATED"


class InvalidTransition(ValueError):
    """Raised when a J/K state transition is not allowed."""


COMMISSION_TRANSITIONS: dict[CommissionStatus, frozenset[CommissionStatus]] = {
    CommissionStatus.ESTIMATE_ONLY: frozenset({CommissionStatus.CONTRACT_PENDING, CommissionStatus.VOIDED}),
    CommissionStatus.CONTRACT_PENDING: frozenset({CommissionStatus.TRIGGER_PENDING, CommissionStatus.VOIDED}),
    CommissionStatus.TRIGGER_PENDING: frozenset({CommissionStatus.ELIGIBLE, CommissionStatus.DISPUTED, CommissionStatus.VOIDED}),
    CommissionStatus.ELIGIBLE: frozenset({CommissionStatus.INVOICED, CommissionStatus.DISPUTED, CommissionStatus.VOIDED}),
    CommissionStatus.INVOICED: frozenset({CommissionStatus.RECEIVED, CommissionStatus.DISPUTED, CommissionStatus.VOIDED}),
    CommissionStatus.RECEIVED: frozenset({CommissionStatus.RECONCILED, CommissionStatus.DISPUTED}),
    CommissionStatus.RECONCILED: frozenset({CommissionStatus.DISPUTED}),
    CommissionStatus.DISPUTED: frozenset({CommissionStatus.TRIGGER_PENDING, CommissionStatus.ELIGIBLE, CommissionStatus.VOIDED}),
    CommissionStatus.VOIDED: frozenset(),
}

MONITORING_TRANSITIONS: dict[MonitoringStatus, frozenset[MonitoringStatus]] = {
    MonitoringStatus.OPEN: frozenset({MonitoringStatus.DUE, MonitoringStatus.WAIVED, MonitoringStatus.ESCALATED}),
    MonitoringStatus.DUE: frozenset({MonitoringStatus.COMPLETED, MonitoringStatus.WAIVED, MonitoringStatus.ESCALATED}),
    MonitoringStatus.ESCALATED: frozenset({MonitoringStatus.DUE, MonitoringStatus.COMPLETED, MonitoringStatus.WAIVED}),
    MonitoringStatus.COMPLETED: frozenset({MonitoringStatus.DUE}),
    MonitoringStatus.WAIVED: frozenset({MonitoringStatus.OPEN, MonitoringStatus.DUE}),
}


@dataclass(frozen=True, slots=True)
class CommissionLedgerEntry:
    commission_id: str
    match_id: str
    beneficiary_tenant_id: str
    contract_id: str | None
    trigger_event: str
    base_amount: Decimal
    rate_bps: int
    estimated_amount: Decimal
    status: CommissionStatus
    currency: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def estimate(
        *,
        match_id: str,
        beneficiary_tenant_id: str,
        trigger_event: str,
        base_amount: Decimal,
        rate_bps: int,
        currency: str = "BRL",
        contract_id: str | None = None,
    ) -> "CommissionLedgerEntry":
        if base_amount < 0:
            raise ValueError("base_amount cannot be negative")
        if not 0 <= rate_bps <= 10_000:
            raise ValueError("rate_bps must be between 0 and 10000")
        if not trigger_event.strip():
            raise ValueError("trigger_event is required")
        now = datetime.now(timezone.utc)
        estimated = (base_amount * Decimal(rate_bps) / Decimal(10_000)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return CommissionLedgerEntry(
            commission_id=str(uuid4()),
            match_id=match_id,
            beneficiary_tenant_id=beneficiary_tenant_id,
            contract_id=contract_id,
            trigger_event=trigger_event,
            base_amount=base_amount,
            rate_bps=rate_bps,
            estimated_amount=estimated,
            status=CommissionStatus.ESTIMATE_ONLY,
            currency=currency,
            created_at=now,
            updated_at=now,
        )

    def transition(
        self,
        status: CommissionStatus,
        *,
        contract_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> "CommissionLedgerEntry":
        if status not in COMMISSION_TRANSITIONS[self.status]:
            raise InvalidTransition(f"commission {self.status} -> {status} is not allowed")
        if status in {CommissionStatus.TRIGGER_PENDING, CommissionStatus.ELIGIBLE} and not (
            contract_id or self.contract_id
        ):
            raise InvalidTransition("contract_id is required before a commission can become triggerable")
        return replace(
            self,
            status=status,
            contract_id=contract_id or self.contract_id,
            metadata={**self.metadata, **(metadata or {})},
            updated_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True, slots=True)
class MonitoringItem:
    monitoring_id: str
    match_id: str
    subject_tenant_id: str
    kind: str
    due_date: date
    status: MonitoringStatus
    owner_agent: str
    source: str
    evidence_required: bool
    last_evidence_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def transition(self, status: MonitoringStatus) -> "MonitoringItem":
        if status not in MONITORING_TRANSITIONS[self.status]:
            raise InvalidTransition(f"monitoring {self.status} -> {status} is not allowed")
        return replace(self, status=status)


class PostClosingLedger:
    """In-memory J/K aggregate for API prototyping and tests."""

    def __init__(self) -> None:
        self._commissions: dict[str, CommissionLedgerEntry] = {}
        self._monitoring: dict[str, MonitoringItem] = {}
        self._lock = RLock()

    def create_commission_estimate(self, **kwargs: object) -> CommissionLedgerEntry:
        entry = CommissionLedgerEntry.estimate(**kwargs)  # type: ignore[arg-type]
        with self._lock:
            self._commissions[entry.commission_id] = entry
        return entry

    def transition_commission(
        self,
        commission_id: str,
        status: CommissionStatus,
        *,
        contract_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> CommissionLedgerEntry:
        with self._lock:
            entry = self._commissions[commission_id]
            updated = entry.transition(status, contract_id=contract_id, metadata=metadata)
            self._commissions[commission_id] = updated
            return updated

    def add_monitoring_item(
        self,
        *,
        match_id: str,
        subject_tenant_id: str,
        kind: str,
        due_date: date,
        owner_agent: str = "GOVERNANCE_AGENT",
        source: str = "POST_CLOSING_CONTRACT",
        evidence_required: bool = True,
        metadata: dict[str, str] | None = None,
    ) -> MonitoringItem:
        item = MonitoringItem(
            monitoring_id=f"monitor-{uuid4()}",
            match_id=match_id,
            subject_tenant_id=subject_tenant_id,
            kind=kind,
            due_date=due_date,
            status=MonitoringStatus.OPEN,
            owner_agent=owner_agent,
            source=source,
            evidence_required=evidence_required,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._monitoring[item.monitoring_id] = item
        return item

    def transition_monitoring(
        self,
        monitoring_id: str,
        status: MonitoringStatus,
        *,
        last_evidence_at: datetime | None = None,
    ) -> MonitoringItem:
        with self._lock:
            item = self._monitoring[monitoring_id]
            updated = item.transition(status)
            if last_evidence_at is not None:
                updated = replace(updated, last_evidence_at=last_evidence_at)
            self._monitoring[monitoring_id] = updated
            return updated

    def due_items(self, *, as_of: date | None = None) -> list[MonitoringItem]:
        as_of = as_of or date.today()
        with self._lock:
            return [
                item
                for item in self._monitoring.values()
                if item.status in {MonitoringStatus.OPEN, MonitoringStatus.DUE}
                and item.due_date <= as_of
            ]

    def commission(self, commission_id: str) -> CommissionLedgerEntry:
        with self._lock:
            return self._commissions[commission_id]

    def monitoring(self, monitoring_id: str) -> MonitoringItem:
        with self._lock:
            return self._monitoring[monitoring_id]

"""Provider-neutral adapters for Open Finance and credit bureaus.

The implementation is deliberately free of provider SDKs and network calls.
A real connector is injected through ``fetcher`` after a provider contract and
consent flow have been approved. The adapter never receives bank credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from app.integrations.consent_ledger import ConsentLedger


class AdapterError(RuntimeError):
    """Base error for an external-data adapter."""


class AdapterNotConfigured(AdapterError):
    """Raised when a production adapter has no provider implementation."""


class ExternalFetcher(Protocol):
    def __call__(self, request: "AdapterRequest") -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    subject_id: str
    tenant_id: str
    consent_id: str
    purpose: str
    scopes: tuple[str, ...]
    period_start: date | None = None
    period_end: date | None = None
    request_id: str = ""
    correlation_id: str = ""

    def with_ids(self) -> "AdapterRequest":
        return AdapterRequest(
            subject_id=self.subject_id,
            tenant_id=self.tenant_id,
            consent_id=self.consent_id,
            purpose=self.purpose,
            scopes=self.scopes,
            period_start=self.period_start,
            period_end=self.period_end,
            request_id=self.request_id or f"request-{uuid4()}",
            correlation_id=self.correlation_id or f"correlation-{uuid4()}",
        )


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    fact: str
    value: Any
    unit: str | None
    as_of: str | None
    source: str
    provider: str
    quality: str
    evidence_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact": self.fact,
            "value": self.value,
            "unit": self.unit,
            "as_of": self.as_of,
            "source": self.source,
            "provider": self.provider,
            "quality": self.quality,
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    provider: str
    source_type: str
    request_id: str
    correlation_id: str
    retrieved_at: datetime
    source_period: str | None
    raw_reference: str
    normalized_facts: tuple[NormalizedFact, ...]
    quality_flags: tuple[str, ...]
    errors: tuple[str, ...]
    consent_id: str
    schema_version: str
    evidence_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_type": self.source_type,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "retrieved_at": self.retrieved_at.isoformat(),
            "source_period": self.source_period,
            "raw_reference": self.raw_reference,
            "normalized_facts": [fact.as_dict() for fact in self.normalized_facts],
            "quality_flags": list(self.quality_flags),
            "errors": list(self.errors),
            "consent_id": self.consent_id,
            "schema_version": self.schema_version,
            "evidence_hash": self.evidence_hash,
        }


class ExternalDataAdapter:
    source_type = "EXTERNAL"
    schema_version = "external-evidence-v1"

    def __init__(
        self,
        *,
        provider: str,
        consent_ledger: ConsentLedger,
        fetcher: ExternalFetcher | None = None,
    ) -> None:
        self.provider = provider
        self.consent_ledger = consent_ledger
        self.fetcher = fetcher

    def fetch(self, request: AdapterRequest) -> AdapterResponse:
        request = request.with_ids()
        self.consent_ledger.validate_and_record_access(
            request.consent_id,
            actor_id=f"adapter:{self.provider}",
            purpose=request.purpose,
            scopes=request.scopes,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
        )
        retrieved_at = datetime.now(timezone.utc)
        if self.fetcher is None:
            raise AdapterNotConfigured(
                f"provider adapter {self.provider!r} has no fetcher; configure the provider outside this prototype"
            )
        raw_payload = dict(self.fetcher(request))
        canonical_payload = json.dumps(raw_payload, sort_keys=True, separators=(",", ":"), default=str)
        evidence_hash = "sha256:" + sha256(canonical_payload.encode("utf-8")).hexdigest()
        facts, quality_flags, errors, source_period = self.normalize(
            raw_payload,
            evidence_hash=evidence_hash,
            retrieved_at=retrieved_at,
        )
        return AdapterResponse(
            provider=self.provider,
            source_type=self.source_type,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            retrieved_at=retrieved_at,
            source_period=source_period,
            raw_reference=f"{self.provider}:{request.request_id}",
            normalized_facts=tuple(facts),
            quality_flags=tuple(quality_flags),
            errors=tuple(errors),
            consent_id=request.consent_id,
            schema_version=self.schema_version,
            evidence_hash=evidence_hash,
        )

    def normalize(
        self,
        raw_payload: Mapping[str, Any],
        *,
        evidence_hash: str,
        retrieved_at: datetime,
    ) -> tuple[list[NormalizedFact], list[str], list[str], str | None]:
        raise NotImplementedError

    def _fact(
        self,
        *,
        fact: str,
        value: Any,
        unit: str | None,
        as_of: str | None,
        quality: str,
        evidence_hash: str,
    ) -> NormalizedFact:
        return NormalizedFact(
            fact=fact,
            value=value,
            unit=unit,
            as_of=as_of,
            source=self.source_type,
            provider=self.provider,
            quality=quality,
            evidence_hash=evidence_hash,
        )


class OpenFinanceAdapter(ExternalDataAdapter):
    source_type = "OPEN_FINANCE"
    schema_version = "open-finance-evidence-v1"

    def normalize(
        self,
        raw_payload: Mapping[str, Any],
        *,
        evidence_hash: str,
        retrieved_at: datetime,
    ) -> tuple[list[NormalizedFact], list[str], list[str], str | None]:
        period = _string_or_none(raw_payload.get("source_period"))
        facts: list[NormalizedFact] = []
        quality_flags: list[str] = []
        errors: list[str] = []
        for key, unit in (
            ("monthly_inflow", "BRL/month"),
            ("monthly_outflow", "BRL/month"),
            ("debt_service_monthly", "BRL/month"),
            ("total_debt", "BRL"),
            ("account_balance", "BRL"),
        ):
            if key in raw_payload:
                facts.append(
                    self._fact(
                        fact=key,
                        value=raw_payload[key],
                        unit=unit,
                        as_of=period,
                        quality=_quality_for(raw_payload, period),
                        evidence_hash=evidence_hash,
                    )
                )
        if not facts:
            quality_flags.append("NO_NORMALIZABLE_FACTS")
        if not period:
            quality_flags.append("SOURCE_PERIOD_MISSING")
        return facts, quality_flags, errors, period


class BureauAdapter(ExternalDataAdapter):
    source_type = "CREDIT_BUREAU"
    schema_version = "credit-bureau-evidence-v1"

    def normalize(
        self,
        raw_payload: Mapping[str, Any],
        *,
        evidence_hash: str,
        retrieved_at: datetime,
    ) -> tuple[list[NormalizedFact], list[str], list[str], str | None]:
        period = _string_or_none(raw_payload.get("source_period"))
        facts: list[NormalizedFact] = []
        quality_flags: list[str] = []
        errors: list[str] = []
        field_units = {
            "credit_score": "points",
            "open_defaults_count": "count",
            "outstanding_debt": "BRL",
            "credit_inquiries_90d": "count",
        }
        for key, unit in field_units.items():
            if key in raw_payload:
                facts.append(
                    self._fact(
                        fact=key,
                        value=raw_payload[key],
                        unit=unit,
                        as_of=period,
                        quality=_quality_for(raw_payload, period),
                        evidence_hash=evidence_hash,
                    )
                )
        if not facts:
            quality_flags.append("NO_NORMALIZABLE_FACTS")
        if not period:
            quality_flags.append("SOURCE_PERIOD_MISSING")
        return facts, quality_flags, errors, period


class DemoOpenFinanceAdapter(OpenFinanceAdapter):
    """Deterministic local adapter used by tests and the preview only."""

    def __init__(self, *, consent_ledger: ConsentLedger) -> None:
        super().__init__(
            provider="demo-open-finance",
            consent_ledger=consent_ledger,
            fetcher=lambda request: {
                "source_period": "2026-07-31",
                "monthly_inflow": 820_000,
                "monthly_outflow": 510_000,
                "debt_service_monthly": 180_000,
                "total_debt": 3_200_000,
                "account_balance": 1_150_000,
            },
        )


class DemoBureauAdapter(BureauAdapter):
    """Deterministic local adapter used by tests and the preview only."""

    def __init__(self, *, consent_ledger: ConsentLedger) -> None:
        super().__init__(
            provider="demo-credit-bureau",
            consent_ledger=consent_ledger,
            fetcher=lambda request: {
                "source_period": "2026-07-31",
                "credit_score": 742,
                "open_defaults_count": 0,
                "outstanding_debt": 3_200_000,
                "credit_inquiries_90d": 2,
            },
        )


def _string_or_none(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _quality_for(raw_payload: Mapping[str, Any], period: str | None) -> str:
    if raw_payload.get("quality") in {"VERIFIED", "PARTIAL", "STALE"}:
        return str(raw_payload["quality"])
    return "VERIFIED_PERIOD" if period else "UNDATED"

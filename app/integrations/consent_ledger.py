"""Consent Ledger prototype for external-data collection.

This module is intentionally provider-agnostic and in-memory. It is a safe
prototype for the domain contract: production must replace the store with
PostgreSQL plus an append-only audit/event table and must never store bank
credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock
from typing import Iterable
from uuid import uuid4


class ConsentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConsentViolation(ValueError):
    """Raised when a collection is outside a valid purpose or scope."""


class ConsentNotFound(KeyError):
    """Raised when a consent identifier is not known by the ledger."""


@dataclass(frozen=True, slots=True)
class ConsentGrant:
    consent_id: str
    subject_id: str
    tenant_id: str
    purpose: str
    scopes: frozenset[str]
    recipient: str
    source_institution: str
    granted_at: datetime
    expires_at: datetime
    status: ConsentStatus = ConsentStatus.ACTIVE
    provider_reference: str | None = None
    revoked_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def usable_for(
        self,
        *,
        purpose: str,
        scopes: Iterable[str],
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(timezone.utc)
        requested_scopes = frozenset(scopes)
        return (
            self.status is ConsentStatus.ACTIVE
            and self.expires_at > now
            and self.purpose == purpose
            and requested_scopes.issubset(self.scopes)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "consent_id": self.consent_id,
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
            "purpose": self.purpose,
            "scopes": sorted(self.scopes),
            "recipient": self.recipient,
            "source_institution": self.source_institution,
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status.value,
            "provider_reference": self.provider_reference,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ConsentAccessEvent:
    access_id: str
    consent_id: str
    actor_id: str
    purpose: str
    scopes: frozenset[str]
    request_id: str
    correlation_id: str
    accessed_at: datetime
    outcome: str = "ALLOWED"

    def as_dict(self) -> dict[str, object]:
        return {
            "access_id": self.access_id,
            "consent_id": self.consent_id,
            "actor_id": self.actor_id,
            "purpose": self.purpose,
            "scopes": sorted(self.scopes),
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "accessed_at": self.accessed_at.isoformat(),
            "outcome": self.outcome,
        }


class ConsentLedger:
    """Thread-safe in-memory consent ledger for local/demo execution."""

    def __init__(self) -> None:
        self._grants: dict[str, ConsentGrant] = {}
        self._access_events: list[ConsentAccessEvent] = []
        self._lock = RLock()

    def issue(
        self,
        *,
        subject_id: str,
        tenant_id: str,
        purpose: str,
        scopes: Iterable[str],
        recipient: str,
        source_institution: str,
        expires_at: datetime,
        granted_at: datetime | None = None,
        provider_reference: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ConsentGrant:
        granted_at = granted_at or datetime.now(timezone.utc)
        if expires_at <= granted_at:
            raise ValueError("expires_at must be after granted_at")
        normalized_scopes = frozenset(scope.strip() for scope in scopes if scope.strip())
        if not normalized_scopes:
            raise ValueError("at least one scope is required")
        grant = ConsentGrant(
            consent_id=f"consent-{uuid4()}",
            subject_id=subject_id,
            tenant_id=tenant_id,
            purpose=purpose,
            scopes=normalized_scopes,
            recipient=recipient,
            source_institution=source_institution,
            granted_at=granted_at,
            expires_at=expires_at,
            provider_reference=provider_reference,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._grants[grant.consent_id] = grant
        return grant

    def get(self, consent_id: str) -> ConsentGrant:
        with self._lock:
            try:
                return self._grants[consent_id]
            except KeyError as exc:
                raise ConsentNotFound(consent_id) from exc

    def revoke(self, consent_id: str, *, revoked_at: datetime | None = None) -> ConsentGrant:
        revoked_at = revoked_at or datetime.now(timezone.utc)
        with self._lock:
            grant = self.get(consent_id)
            revoked = replace(grant, status=ConsentStatus.REVOKED, revoked_at=revoked_at)
            self._grants[consent_id] = revoked
            return revoked

    def validate_and_record_access(
        self,
        consent_id: str,
        *,
        actor_id: str,
        purpose: str,
        scopes: Iterable[str],
        request_id: str,
        correlation_id: str,
        accessed_at: datetime | None = None,
    ) -> ConsentGrant:
        accessed_at = accessed_at or datetime.now(timezone.utc)
        requested_scopes = frozenset(scopes)
        with self._lock:
            grant = self.get(consent_id)
            if not grant.usable_for(purpose=purpose, scopes=requested_scopes, now=accessed_at):
                raise ConsentViolation(
                    "consent is revoked, expired, outside purpose, or missing requested scope"
                )
            self._access_events.append(
                ConsentAccessEvent(
                    access_id=f"access-{uuid4()}",
                    consent_id=consent_id,
                    actor_id=actor_id,
                    purpose=purpose,
                    scopes=requested_scopes,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    accessed_at=accessed_at,
                )
            )
            return grant

    def access_events(self, consent_id: str | None = None) -> list[ConsentAccessEvent]:
        with self._lock:
            events = self._access_events
            if consent_id is not None:
                events = [event for event in events if event.consent_id == consent_id]
            return list(events)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "grants": [grant.as_dict() for grant in self._grants.values()],
                "access_events": [event.as_dict() for event in self._access_events],
            }

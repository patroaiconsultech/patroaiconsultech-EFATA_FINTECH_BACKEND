"""Read-only ERP adapter boundary.

Provider-specific endpoint paths are supplied by an approved resource map. The
adapter never performs writes and never persists raw ERP payloads. It returns
only operational metadata and evidence hashes; a downstream import pipeline can
store minimized, normalized records after consent and reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
from hashlib import sha256
import json
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

import httpx


class ERPAdapterError(RuntimeError):
    """Base error for ERP connector failures."""


class ERPAdapterNotConfigured(ERPAdapterError):
    """Raised when a provider contract is not configured for the tenant."""


class ERPAdapterSecurityError(ERPAdapterError):
    """Raised when a URL, scope or credential boundary is unsafe."""


@dataclass(frozen=True, slots=True)
class ERPResourceEvidence:
    resource: str
    endpoint: str
    records_seen: int
    payload_hash: str
    retrieved_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "endpoint": self.endpoint,
            "records_seen": self.records_seen,
            "payload_hash": self.payload_hash,
            "retrieved_at": self.retrieved_at,
        }


@dataclass(frozen=True, slots=True)
class ERPSyncResult:
    provider: str
    external_tenant: str
    records_seen: int
    resources: tuple[ERPResourceEvidence, ...]
    cursor: str | None
    warnings: tuple[str, ...]
    normalized_inputs: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "external_tenant": self.external_tenant,
            "records_seen": self.records_seen,
            "resources": [resource.as_dict() for resource in self.resources],
            "cursor": self.cursor,
            "warnings": list(self.warnings),
            "normalized_input_keys": sorted(self.normalized_inputs.keys()),
        }

    @staticmethod
    def _merge_normalized_inputs(target: dict[str, Any], resource: str, records: list[Any]) -> None:
        """Map only safe aggregate fields into the M1 input contract."""
        if not records or not all(isinstance(record, dict) for record in records):
            return

        def first(record: dict[str, Any], *keys: str) -> Any:
            for key in keys:
                if key in record and record[key] not in (None, ""):
                    return record[key]
            return None

        def number(value: Any) -> float | None:
            if value in (None, ""):
                return None
            try:
                return float(str(value).replace(".", "").replace(",", "."))
            except (TypeError, ValueError):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

        if resource in {"projects", "phases"}:
            record = records[0]
            physical = target.setdefault("physical", {})
            for destination, keys in {
                "units": ("units", "unit_count", "total_units", "quantidade_unidades"),
                "area_equivalent_m2": ("area_equivalent_m2", "equivalent_area", "area_equivalente"),
                "area_total_m2": ("area_total_m2", "total_area", "area_total"),
            }.items():
                value = number(first(record, *keys))
                if value is not None:
                    physical[destination] = value
            project_name = first(record, "name", "project_name", "empreendimento")
            if project_name:
                target.setdefault("project", {})["name"] = str(project_name)
        elif resource == "units":
            physical = target.setdefault("physical", {})
            physical["units"] = len(records)
            areas = [number(first(record, "area", "private_area", "area_privativa")) for record in records]
            areas = [value for value in areas if value is not None]
            if areas:
                physical["private_area_total_m2"] = sum(areas)
            statuses = [str(first(record, "status", "situacao") or "").upper() for record in records]
            target.setdefault("revenue", {})["available_units"] = sum(status in {"AVAILABLE", "ESTOQUE", "STOCK"} for status in statuses)
        elif resource in {"sales_contracts", "receivables", "receivable_installments"}:
            revenue = target.setdefault("revenue", {})
            amounts = [number(first(record, "amount", "value", "total", "valor", "valor_total")) for record in records]
            amounts = [value for value in amounts if value is not None]
            if amounts:
                key = "contracted_sales_total" if resource == "sales_contracts" else "receivables_total"
                revenue[key] = round(sum(amounts), 2)
            if resource == "sales_contracts":
                revenue["sold_units"] = len(records)
        elif resource == "costs":
            costs = target.setdefault("costs", {})
            totals = [number(first(record, "amount", "value", "total", "valor", "valor_total")) for record in records]
            totals = [value for value in totals if value is not None]
            if totals:
                costs["other_total"] = round(sum(totals), 2)
        elif resource == "construction_schedule":
            schedule = target.setdefault("timeline", {})
            schedule["months"] = len(records)
            values = [number(first(record, "amount", "cost", "value", "valor")) for record in records]
            values = [value for value in values if value is not None]
            if values:
                costs = target.setdefault("costs", {})
                costs["construction_schedule"] = [round(value, 2) for value in values]


class ReadOnlyERPAdapter:
    """Small HTTP boundary with explicit provider routes and no write methods."""

    allowed_providers = {"SIENGE", "MEGA"}
    allowed_resource_names = {
        "enterprises",
        "projects",
        "phases",
        "units",
        "customers",
        "sales_contracts",
        "receivables",
        "receivable_installments",
        "inventory",
        "exchanges",
        "costs",
        "construction_schedule",
        "debts",
    }

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        external_tenant: str,
        secret: str,
        resource_map: Mapping[str, str],
        timeout_seconds: float = 10.0,
        max_records: int = 5000,
        allowed_hosts: str = "",
        http_client: httpx.Client | None = None,
    ) -> None:
        self.provider = provider.upper()
        self.base_url = base_url.rstrip("/") + "/"
        self.external_tenant = external_tenant
        self.secret = secret
        self.resource_map = dict(resource_map)
        self.timeout_seconds = timeout_seconds
        self.max_records = max_records
        self.allowed_hosts = {
            host.strip().lower()
            for host in allowed_hosts.split(",")
            if host.strip()
        }
        self.http_client = http_client
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if self.provider not in self.allowed_providers:
            raise ERPAdapterNotConfigured(f"Unsupported ERP provider: {self.provider}")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ERPAdapterSecurityError("ERP base URL must use HTTPS and contain a hostname.")
        if self.allowed_hosts and parsed.hostname.lower() not in self.allowed_hosts:
            raise ERPAdapterSecurityError("ERP host is not present in the configured allowlist.")
        if not self.resource_map:
            raise ERPAdapterNotConfigured("No approved ERP resource map is configured.")
        if self.max_records < 1 or self.max_records > 100_000:
            raise ERPAdapterSecurityError("ERP max_records is outside the safe range.")
        for resource, path in self.resource_map.items():
            if resource not in self.allowed_resource_names:
                raise ERPAdapterSecurityError(f"ERP resource is not allowed: {resource}")
            parsed_path = urlparse(path)
            if (
                not path.startswith("/")
                or path.startswith("//")
                or parsed_path.netloc
                or ".." in path
                or "://" in path
            ):
                raise ERPAdapterSecurityError(f"ERP resource path is unsafe: {path}")

    def _headers(self) -> dict[str, str]:
        # Sienge commonly uses a dedicated Basic credential; Mega deployments
        # may use a bearer token. The credential is decrypted only in memory.
        if self.provider == "SIENGE" and ":" in self.secret:
            value = base64.b64encode(self.secret.encode("utf-8")).decode("ascii")
            authorization = f"Basic {value}"
        else:
            authorization = f"Bearer {self.secret}"
        return {
            "Authorization": authorization,
            "Accept": "application/json",
            "X-External-Tenant": self.external_tenant,
        }

    @staticmethod
    def _records(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "items", "results", "content", "records"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def _payload_hash(payload: Any) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()

    def sync(self, *, request_id: str, correlation_id: str) -> ERPSyncResult:
        client = self.http_client or httpx.Client(timeout=self.timeout_seconds, follow_redirects=False)
        close_client = self.http_client is None
        evidence: list[ERPResourceEvidence] = []
        warnings: list[str] = []
        records_seen = 0
        normalized_inputs: dict[str, Any] = {}
        retrieved_at = datetime.now(timezone.utc).isoformat()
        try:
            for resource, path in self.resource_map.items():
                url = urljoin(self.base_url, path.lstrip("/"))
                response = client.get(
                    url,
                    headers=self._headers() | {
                        "X-Request-ID": request_id,
                        "X-Correlation-ID": correlation_id,
                    },
                    params={"limit": self.max_records},
                )
                response.raise_for_status()
                payload = response.json()
                records = self._records(payload)
                if len(records) > self.max_records:
                    raise ERPAdapterSecurityError(
                        f"ERP resource {resource} exceeded max_records={self.max_records}."
                    )
                records_seen += len(records)
                ERPSyncResult._merge_normalized_inputs(normalized_inputs, resource, records)
                evidence.append(
                    ERPResourceEvidence(
                        resource=resource,
                        endpoint=path,
                        records_seen=len(records),
                        payload_hash=self._payload_hash(payload),
                        retrieved_at=retrieved_at,
                    )
                )
                if not records:
                    warnings.append(f"ERP resource {resource} returned no normalizable records.")
        except httpx.HTTPStatusError as exc:
            raise ERPAdapterError(
                f"ERP provider returned HTTP {exc.response.status_code} for a read-only request."
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ERPAdapterError("ERP provider request failed or returned invalid JSON.") from exc
        finally:
            if close_client:
                client.close()
        return ERPSyncResult(
            provider=self.provider,
            external_tenant=self.external_tenant,
            records_seen=records_seen,
            resources=tuple(evidence),
            cursor=None,
            warnings=tuple(warnings),
            normalized_inputs=normalized_inputs,
        )

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class M2MErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class M2MResponseMeta(BaseModel):
    api_version: str = "v1"
    contract_version: str = "m2m-r1"
    service_version: str | None = None
    release_sha: str | None = None


class M2MResponseEnvelope(BaseModel):
    ok: bool = True
    request_id: str
    execution_id: str
    correlation_id: str
    tenant_id: str
    capability: str
    status: str = "completed"
    data: Any
    error: M2MErrorBody | None = None
    meta: M2MResponseMeta


class M2MCapabilityView(BaseModel):
    scope: str
    method: str
    path: str
    nature: str
    tenant_required: bool
    write: bool


class M2MAuditEventView(BaseModel):
    audit_event_id: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    request_id: str
    correlation_id: str
    occurred_at: datetime


class M2MAuditPage(BaseModel):
    items: list[M2MAuditEventView]
    next_cursor: str | None = None

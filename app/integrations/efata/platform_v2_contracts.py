from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EfataV2Thread(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str


class EfataV2MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    agent: str = Field(default="Josué", max_length=160)


class EfataV2ResponseEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: str
    execution_id: str
    thread_id: str
    tenant_id: str
    agent_id: str
    agent_name: str
    display_name: str
    final_speaker_agent_id: str
    turn_owner_agent_id: str
    route_family: str
    content: str
    status: str
    error: str | None = None
    token_usage: dict[str, int] | None = None
    latency_ms: int | None = None
    created_at: datetime


class EfataV2ExecutionMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    execution_id: str
    resolved_target: str
    turn_owner: str
    display_agent_id: str
    execution_engine: str
    ownership_locked: bool


class EfataV2MessageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: str
    execution_id: str
    agent_id: str
    agent_name: str
    content: str
    execution: EfataV2ExecutionMetadata
    response: EfataV2ResponseEnvelope


class EfataV2StreamEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: Literal[
        "status",
        "execution",
        "agent_started",
        "chunk",
        "agent_chunk",
        "agent_done",
        "error",
        "done",
    ]
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def execution_id(self) -> str | None:
        value = self.data.get("execution_id")
        return str(value) if value is not None else None

    @property
    def sequence(self) -> int | None:
        value = self.data.get("sequence")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class EfataV2KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    logical_document_id: str | None = None
    version: int | None = None
    scope: str
    title: str
    filename: str
    classification: str
    status: str
    allowed_purposes: list[str] = Field(default_factory=list)


class EfataV2BridgeSnapshot(BaseModel):
    schema_version: str = "fintech-efata-v2-bridge-snapshot-1"
    health: dict[str, Any]
    ready: dict[str, Any]
    tools_capabilities: dict[str, Any] | list[Any]
    realtime_capabilities: dict[str, Any] | list[Any]


class EfataV2RequestObservation(BaseModel):
    request_id: str
    correlation_id: str
    method: str
    path: str
    status_code: int | None = None
    duration_ms: float
    result_code: str

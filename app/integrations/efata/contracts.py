from typing import Literal

from pydantic import BaseModel, Field


class EfataExecutionRequest(BaseModel):
    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    capability_id: str
    purpose: str
    data_classification: Literal[
        "PUBLIC",
        "INTERNAL",
        "CONFIDENTIAL",
        "RESTRICTED",
        "REGULATED",
    ]
    persist_to_platform_memory: bool = False
    write_allowed: bool = False
    execution_allowed: bool = True
    payload: dict = Field(default_factory=dict)


class EfataExecutionEnvelope(BaseModel):
    schema_version: str = "fintech-efata-r4-v1"
    message_id: str
    request_id: str
    execution_id: str
    correlation_id: str
    tenant_id: str
    capability_id: str
    status: Literal["accepted", "running", "completed", "failed", "cancelled"]
    content: dict = Field(default_factory=dict)
    error: dict | None = None


class EfataStreamEvent(BaseModel):
    event: Literal[
        "status",
        "execution",
        "agent_started",
        "chunk",
        "agent_done",
        "error",
        "cancelled",
        "done",
    ]
    execution_id: str
    sequence: int
    payload: dict = Field(default_factory=dict)

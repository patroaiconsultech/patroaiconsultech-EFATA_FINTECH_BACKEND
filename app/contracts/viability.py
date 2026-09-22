from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas import ApiModel


ScenarioKey = Literal["BASE", "CONSERVATIVE", "OPTIMISTIC", "STRESS"]


class ViabilityStudyCreate(ApiModel):
    title: str = Field(min_length=3, max_length=255)
    project_name: str = Field(min_length=2, max_length=255)
    base_date: date
    opportunity_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class ViabilityStudyRead(ApiModel):
    study_id: str
    tenant_id: str
    opportunity_id: str | None
    title: str
    project_name: str
    status: str
    base_date: datetime
    currency: str
    inputs_json: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


class ViabilityScenarioCreate(ApiModel):
    scenario_key: ScenarioKey = "BASE"
    name: str = Field(min_length=2, max_length=120)
    overrides: dict[str, Any] = Field(default_factory=dict)


class ViabilityScenarioRead(ApiModel):
    scenario_id: str
    study_id: str
    scenario_key: str
    name: str
    status: str
    overrides_json: dict[str, Any]
    outputs_json: dict[str, Any]
    engine_version: str
    created_by: str
    created_at: datetime
    calculated_at: datetime | None


class ViabilityFlowRead(ApiModel):
    period_start: date
    revenue: Decimal
    equity_contribution: Decimal
    funding_draw: Decimal
    land_cost: Decimal
    construction_cost: Decimal
    other_costs: Decimal
    interest: Decimal
    principal: Decimal
    project_cash_flow: Decimal
    net_cash_flow: Decimal
    cumulative_cash_flow: Decimal
    debt_balance: Decimal
    discount_factor: Decimal
    present_value: Decimal
    unlevered_present_value: Decimal


class ViabilityCalculationRead(ApiModel):
    scenario: ViabilityScenarioRead
    outputs: dict[str, Any]
    flow: list[ViabilityFlowRead]
    warnings: list[str]


class SensitivityRequest(ApiModel):
    variable: Literal["price", "construction_cost", "funding_rate", "delay_months", "absorption"]
    shocks: list[Decimal] = Field(min_length=1, max_length=15)

    @field_validator("shocks")
    @classmethod
    def validate_shocks(cls, values: list[Decimal]) -> list[Decimal]:
        if any(abs(value) > Decimal("10") for value in values):
            raise ValueError("O choque de sensibilidade deve estar entre -1000% e 1000%.")
        return values


class SensitivityRead(ApiModel):
    variable: str
    results: list[dict[str, Any]]


class ViabilitySnapshotRead(ApiModel):
    snapshot_id: str
    study_id: str
    scenario_id: str
    snapshot_hash: str
    payload_json: dict[str, Any]
    created_by: str
    created_at: datetime
    status: str


class ERPApplySyncRequest(ApiModel):
    confirm: bool = Field(default=False)


class ERPConnectionCreate(ApiModel):
    provider: Literal["SIENGE", "MEGA"]
    external_tenant: str = Field(min_length=2, max_length=255)
    base_url: str = Field(min_length=8, max_length=512)
    scopes: list[str] = Field(default_factory=lambda: ["READ_ONLY"])
    resource_map: dict[str, str] = Field(default_factory=dict)
    secret: str = Field(min_length=8, max_length=4096)


class ERPConnectionRead(ApiModel):
    connection_id: str
    tenant_id: str
    provider: str
    external_tenant: str
    base_url: str
    scopes: list[str]
    resource_map_json: dict[str, str]
    secret_key_version: str
    status: str
    last_sync_at: datetime | None
    created_by: str
    created_at: datetime
    revoked_at: datetime | None


class SyncJobRead(ApiModel):
    sync_job_id: str
    connection_id: str
    study_id: str | None
    tenant_id: str
    status: str
    mode: str
    records_seen: int
    records_imported: int
    error_code: str | None
    error_message: str | None
    result_json: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None

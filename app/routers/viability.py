from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.contracts.viability import (
    ERPApplySyncRequest,
    ERPConnectionCreate,
    ERPConnectionRead,
    SensitivityRead,
    SensitivityRequest,
    SyncJobRead,
    ViabilityCalculationRead,
    ViabilityFlowRead,
    ViabilityScenarioCreate,
    ViabilityScenarioRead,
    ViabilitySnapshotRead,
    ViabilityStudyCreate,
    ViabilityStudyRead,
)
from app.db import get_db
from app.config import Settings, get_settings
from app.erp_adapters import ERPAdapterError, ReadOnlyERPAdapter
from app.errors import ApiError
from app.models import (
    ERPConnection,
    IntegrationSyncJob,
    ViabilityMonthlyFlow,
    ViabilityScenario,
    ViabilitySnapshot,
    ViabilityStudy,
)
from app.secret_cipher import KEY_VERSION, decrypt_secret, encrypt_secret
from app.security import SecurityContext, require_security_context
from app.viability_engine import calculate, sensitivity_matrix

router = APIRouter(prefix="/api/v1/viability", tags=["viability"])

INTERNAL_ROLES = {"ANALYST", "PLATFORM_ADMIN", "INTERNAL_AGENT", "CREDIT_ANALYST"}
CLIENT_ROLES = {"ORIGINATOR_ADMIN", "CLIENT_ADMIN", "BORROWER_ADMIN", "BORROWER_EDITOR"}
PARTNER_ROLES = {"PARTNER_ADMIN", "PARTNER_EDITOR"}


def _require(context: SecurityContext, roles: set[str]) -> None:
    if context.role not in roles:
        raise ApiError(403, "ROLE_NOT_ALLOWED", "Acesso não autorizado.")


def _audit(db: Session, request: Request, context: SecurityContext, action: str, resource_type: str, resource_id: str) -> None:
    record_audit(
        db,
        context=context,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
    )


def _merge_patch(original: dict, patch: dict) -> dict:
    merged = dict(original)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_patch(merged[key], value)
        else:
            merged[key] = value
    return merged


def _study(db: Session, context: SecurityContext, study_id: str) -> ViabilityStudy:
    query = select(ViabilityStudy).where(ViabilityStudy.study_id == study_id)
    if context.role not in INTERNAL_ROLES:
        query = query.where(ViabilityStudy.tenant_id == context.tenant_id)
    study = db.scalar(query)
    if study is None:
        raise ApiError(404, "VIABILITY_STUDY_NOT_FOUND", "Estudo de viabilidade não encontrado.")
    return study


@router.post("/studies", response_model=ViabilityStudyRead, status_code=201)
def create_study(
    payload: ViabilityStudyCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ViabilityStudy:
    _require(context, CLIENT_ROLES | PARTNER_ROLES | INTERNAL_ROLES)
    study = ViabilityStudy(
        tenant_id=context.tenant_id,
        opportunity_id=payload.opportunity_id,
        title=payload.title,
        project_name=payload.project_name,
        base_date=datetime.combine(payload.base_date, datetime.min.time(), tzinfo=timezone.utc),
        currency="BRL",
        inputs_json={**payload.inputs, "base_date": payload.base_date.isoformat()},
        created_by=context.user_id,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(study)
    db.flush()
    _audit(db, request, context, "VIABILITY_STUDY_CREATED", "VIABILITY_STUDY", study.study_id)
    db.commit()
    db.refresh(study)
    return study


@router.get("/studies", response_model=list[ViabilityStudyRead])
def list_studies(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[ViabilityStudy]:
    query = select(ViabilityStudy)
    if context.role not in INTERNAL_ROLES:
        query = query.where(ViabilityStudy.tenant_id == context.tenant_id)
    return list(db.scalars(query.order_by(ViabilityStudy.updated_at.desc())).all())


@router.post("/studies/{study_id}/scenarios", response_model=ViabilityScenarioRead, status_code=201)
def create_scenario(
    study_id: str,
    payload: ViabilityScenarioCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ViabilityScenario:
    _require(context, CLIENT_ROLES | PARTNER_ROLES | INTERNAL_ROLES)
    _study(db, context, study_id)
    existing = db.scalar(
        select(ViabilityScenario).where(
            ViabilityScenario.study_id == study_id,
            ViabilityScenario.scenario_key == payload.scenario_key,
        )
    )
    if existing is not None:
        raise ApiError(409, "VIABILITY_SCENARIO_EXISTS", "O cenário já existe para este estudo.")
    scenario = ViabilityScenario(
        study_id=study_id,
        scenario_key=payload.scenario_key,
        name=payload.name,
        overrides_json=payload.overrides,
        outputs_json={},
        created_by=context.user_id,
    )
    db.add(scenario)
    db.flush()
    _audit(db, request, context, "VIABILITY_SCENARIO_CREATED", "VIABILITY_SCENARIO", scenario.scenario_id)
    db.commit()
    db.refresh(scenario)
    return scenario


@router.get("/studies/{study_id}/scenarios", response_model=list[ViabilityScenarioRead])
def list_scenarios(
    study_id: str,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[ViabilityScenario]:
    _study(db, context, study_id)
    return list(
        db.scalars(
            select(ViabilityScenario)
            .where(ViabilityScenario.study_id == study_id)
            .order_by(ViabilityScenario.created_at.asc())
        ).all()
    )


@router.post("/studies/{study_id}/scenarios/{scenario_key}/calculate", response_model=ViabilityCalculationRead)
def calculate_scenario(
    study_id: str,
    scenario_key: str,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ViabilityCalculationRead:
    _require(context, CLIENT_ROLES | PARTNER_ROLES | INTERNAL_ROLES)
    study = _study(db, context, study_id)
    scenario = db.scalar(
        select(ViabilityScenario).where(
            ViabilityScenario.study_id == study_id,
            ViabilityScenario.scenario_key == scenario_key.upper(),
        )
    )
    if scenario is None:
        raise ApiError(404, "VIABILITY_SCENARIO_NOT_FOUND", "Cenário de viabilidade não encontrado.")
    try:
        result = calculate(study.inputs_json, scenario.overrides_json)
    except ValueError as exc:
        raise ApiError(422, "VIABILITY_INPUT_INVALID", str(exc)) from exc
    scenario.outputs_json = result.outputs
    scenario.status = "CALCULATED"
    scenario.calculated_at = datetime.now(timezone.utc)
    db.execute(delete(ViabilityMonthlyFlow).where(ViabilityMonthlyFlow.scenario_id == scenario.scenario_id))
    for row in result.flow:
        db.add(
            ViabilityMonthlyFlow(
                scenario_id=scenario.scenario_id,
                period_start=datetime.fromisoformat(row["period_start"]).replace(tzinfo=timezone.utc),
                revenue=Decimal(str(row["revenue"])),
                equity_contribution=Decimal(str(row["equity_contribution"])),
                funding_draw=Decimal(str(row["funding_draw"])),
                land_cost=Decimal(str(row["land_cost"])),
                construction_cost=Decimal(str(row["construction_cost"])),
                other_costs=Decimal(str(row["other_costs"])),
                interest=Decimal(str(row["interest"])),
                principal=Decimal(str(row["principal"])),
                net_cash_flow=Decimal(str(row["net_cash_flow"])),
                cumulative_cash_flow=Decimal(str(row["cumulative_cash_flow"])),
                discount_factor=Decimal(str(row["discount_factor"])),
                present_value=Decimal(str(row["present_value"])),
                project_cash_flow=Decimal(str(row["project_cash_flow"])),
                debt_balance=Decimal(str(row["debt_balance"])),
                unlevered_present_value=Decimal(str(row["unlevered_present_value"])),
            )
        )
    _audit(db, request, context, "VIABILITY_SCENARIO_CALCULATED", "VIABILITY_SCENARIO", scenario.scenario_id)
    db.commit()
    db.refresh(scenario)
    return ViabilityCalculationRead(
        scenario=ViabilityScenarioRead.model_validate(scenario),
        outputs=result.outputs,
        flow=[ViabilityFlowRead(**row) for row in result.flow],
        warnings=result.warnings,
    )


@router.post("/studies/{study_id}/scenarios/{scenario_key}/sensitivity", response_model=SensitivityRead)
def calculate_sensitivity(
    study_id: str,
    scenario_key: str,
    payload: SensitivityRequest,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> SensitivityRead:
    _require(context, INTERNAL_ROLES | CLIENT_ROLES | PARTNER_ROLES)
    study = _study(db, context, study_id)
    scenario = db.scalar(
        select(ViabilityScenario).where(
            ViabilityScenario.study_id == study_id,
            ViabilityScenario.scenario_key == scenario_key.upper(),
        )
    )
    if scenario is None:
        raise ApiError(404, "VIABILITY_SCENARIO_NOT_FOUND", "Cenário de viabilidade não encontrado.")
    results = sensitivity_matrix(study.inputs_json | scenario.overrides_json, payload.variable, payload.shocks)
    return SensitivityRead(variable=payload.variable, results=results)


@router.post("/studies/{study_id}/scenarios/{scenario_key}/snapshot", response_model=ViabilitySnapshotRead, status_code=201)
def create_snapshot(
    study_id: str,
    scenario_key: str,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ViabilitySnapshot:
    _require(context, INTERNAL_ROLES)
    study = _study(db, context, study_id)
    scenario = db.scalar(
        select(ViabilityScenario).where(
            ViabilityScenario.study_id == study_id,
            ViabilityScenario.scenario_key == scenario_key.upper(),
            ViabilityScenario.status == "CALCULATED",
        )
    )
    if scenario is None:
        raise ApiError(409, "VIABILITY_SCENARIO_NOT_CALCULATED", "Calcule o cenário antes de congelar o snapshot.")
    flow = list(
        db.scalars(
            select(ViabilityMonthlyFlow)
            .where(ViabilityMonthlyFlow.scenario_id == scenario.scenario_id)
            .order_by(ViabilityMonthlyFlow.period_start.asc())
        ).all()
    )
    payload = {
        "study": study.inputs_json,
        "scenario": scenario.outputs_json,
        "scenario_key": scenario.scenario_key,
        "flow": [
            {
                "period_start": row.period_start.isoformat(),
                "revenue": str(row.revenue),
                "equity_contribution": str(row.equity_contribution),
                "funding_draw": str(row.funding_draw),
                "land_cost": str(row.land_cost),
                "construction_cost": str(row.construction_cost),
                "other_costs": str(row.other_costs),
                "interest": str(row.interest),
                "principal": str(row.principal),
                "project_cash_flow": str(row.project_cash_flow),
                "net_cash_flow": str(row.net_cash_flow),
                "cumulative_cash_flow": str(row.cumulative_cash_flow),
                "debt_balance": str(row.debt_balance),
                "discount_factor": str(row.discount_factor),
                "present_value": str(row.present_value),
                "unlevered_present_value": str(row.unlevered_present_value),
            }
            for row in flow
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    snapshot = ViabilitySnapshot(
        study_id=study_id,
        scenario_id=scenario.scenario_id,
        snapshot_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        payload_json=payload,
        created_by=context.user_id,
    )
    db.add(snapshot)
    db.flush()
    _audit(db, request, context, "VIABILITY_SNAPSHOT_CREATED", "VIABILITY_SNAPSHOT", snapshot.snapshot_id)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.post("/erp-connections", response_model=ERPConnectionRead, status_code=201)
def create_erp_connection(
    payload: ERPConnectionCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ERPConnection:
    _require(context, CLIENT_ROLES | INTERNAL_ROLES)
    if "READ_ONLY" not in {scope.upper() for scope in payload.scopes}:
        raise ApiError(422, "ERP_READ_ONLY_REQUIRED", "A primeira versão aceita apenas escopo READ_ONLY.")
    parsed_base_url = urlparse(payload.base_url)
    if parsed_base_url.scheme not in {"https"} and settings.app_env == "production":
        raise ApiError(422, "ERP_HTTPS_REQUIRED", "Conexões ERP em produção exigem HTTPS.")
    if not parsed_base_url.netloc:
        raise ApiError(422, "ERP_BASE_URL_INVALID", "A URL base do ERP é inválida.")
    existing = db.scalar(
        select(ERPConnection).where(
            ERPConnection.tenant_id == context.tenant_id,
            ERPConnection.provider == payload.provider,
            ERPConnection.external_tenant == payload.external_tenant,
        )
    )
    if existing is not None:
        raise ApiError(409, "ERP_CONNECTION_EXISTS", "A conexão ERP já existe para este ambiente.")
    connection = ERPConnection(
        tenant_id=context.tenant_id,
        provider=payload.provider,
        external_tenant=payload.external_tenant,
        base_url=payload.base_url.rstrip("/"),
        scopes=list(dict.fromkeys(scope.upper() for scope in payload.scopes)),
        resource_map_json=payload.resource_map,
        secret_ciphertext=encrypt_secret(payload.secret),
        secret_key_version=KEY_VERSION,
        status="PENDING_HOMOLOGATION",
        created_by=context.user_id,
    )
    db.add(connection)
    db.flush()
    _audit(db, request, context, "ERP_CONNECTION_CREATED", "ERP_CONNECTION", connection.connection_id)
    db.commit()
    db.refresh(connection)
    return connection


@router.post("/erp-connections/{connection_id}/sync/run", response_model=SyncJobRead, status_code=200)
def run_erp_sync(
    connection_id: str,
    request: Request,
    study_id: str | None = None,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IntegrationSyncJob:
    _require(context, CLIENT_ROLES | INTERNAL_ROLES)
    query = select(ERPConnection).where(ERPConnection.connection_id == connection_id)
    if context.role not in INTERNAL_ROLES:
        query = query.where(ERPConnection.tenant_id == context.tenant_id)
    connection = db.scalar(query)
    if connection is None:
        raise ApiError(404, "ERP_CONNECTION_NOT_FOUND", "Conexão ERP não encontrada.")
    if connection.status == "REVOKED":
        raise ApiError(409, "ERP_CONNECTION_REVOKED", "A conexão ERP foi revogada.")
    if study_id is not None:
        study = _study(db, context, study_id)
        if study.tenant_id != connection.tenant_id:
            raise ApiError(404, "VIABILITY_STUDY_NOT_FOUND", "Estudo de viabilidade não encontrado.")
    if settings.app_env == "production" and not settings.erp_allowed_hosts.strip():
        raise ApiError(503, "ERP_HOST_ALLOWLIST_NOT_CONFIGURED", "A allowlist de hosts ERP não está configurada.")

    job = IntegrationSyncJob(
        connection_id=connection_id,
        study_id=study_id,
        tenant_id=connection.tenant_id,
        mode="READ_ONLY",
        status="RUNNING",
    )
    connection.status = "SYNCING"
    db.add(job)
    db.flush()
    try:
        adapter = ReadOnlyERPAdapter(
            provider=connection.provider,
            base_url=connection.base_url,
            external_tenant=connection.external_tenant,
            secret=decrypt_secret(connection.secret_ciphertext),
            resource_map=connection.resource_map_json,
            timeout_seconds=settings.erp_http_timeout_seconds,
            max_records=settings.erp_max_records_per_resource,
            allowed_hosts=settings.erp_allowed_hosts,
        )
        result = adapter.sync(
            request_id=request.state.request_id,
            correlation_id=request.state.correlation_id,
        )
        job.status = "SUCCEEDED"
        job.records_seen = result.records_seen
        job.records_imported = 0
        job.cursor = result.cursor
        job.result_json = result.as_dict() | {"normalized_inputs": result.normalized_inputs}
        connection.status = "ACTIVE"
        connection.last_sync_at = datetime.now(timezone.utc)
    except ERPAdapterError as exc:
        job.status = "FAILED"
        job.error_code = "ERP_SYNC_FAILED"
        job.error_message = str(exc)
        job.result_json = {}
        connection.status = "ERROR"
    _audit(db, request, context, "ERP_SYNC_EXECUTED", "ERP_CONNECTION", connection_id)
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


@router.post("/erp-sync-jobs/{sync_job_id}/apply", response_model=ViabilityStudyRead, status_code=200)
def apply_erp_sync(
    sync_job_id: str,
    payload: ERPApplySyncRequest,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> ViabilityStudy:
    _require(context, CLIENT_ROLES | INTERNAL_ROLES)
    if not payload.confirm:
        raise ApiError(422, "ERP_APPLY_CONFIRMATION_REQUIRED", "Confirme explicitamente a aplicação do snapshot ERP.")
    query = select(IntegrationSyncJob).where(IntegrationSyncJob.sync_job_id == sync_job_id)
    if context.role not in INTERNAL_ROLES:
        query = query.where(IntegrationSyncJob.tenant_id == context.tenant_id)
    job = db.scalar(query)
    if job is None:
        raise ApiError(404, "ERP_SYNC_JOB_NOT_FOUND", "Job de sincronização ERP não encontrado.")
    if job.status not in {"SUCCEEDED", "APPLIED"} or not job.study_id:
        raise ApiError(409, "ERP_SYNC_NOT_APPLICABLE", "Somente uma sincronização concluída vinculada a estudo pode ser aplicada.")
    study = _study(db, context, job.study_id)
    normalized_inputs = (job.result_json or {}).get("normalized_inputs", {})
    if not isinstance(normalized_inputs, dict) or not normalized_inputs:
        raise ApiError(409, "ERP_SYNC_EMPTY_PATCH", "A sincronização não produziu dados canônicos aplicáveis.")
    if job.status != "APPLIED":
        study.inputs_json = _merge_patch(study.inputs_json, normalized_inputs)
        study.updated_at = datetime.now(timezone.utc)
        job.status = "APPLIED"
        job.records_imported = len(normalized_inputs)
        _audit(db, request, context, "ERP_SYNC_APPLIED", "VIABILITY_STUDY", study.study_id)
        db.commit()
        db.refresh(study)
    return study


@router.get("/erp-connections", response_model=list[ERPConnectionRead])
def list_erp_connections(
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> list[ERPConnection]:
    query = select(ERPConnection)
    if context.role not in INTERNAL_ROLES:
        query = query.where(ERPConnection.tenant_id == context.tenant_id)
    return list(db.scalars(query.order_by(ERPConnection.created_at.desc())).all())


@router.post("/erp-connections/{connection_id}/sync", response_model=SyncJobRead, status_code=202)
def request_erp_sync(
    connection_id: str,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> IntegrationSyncJob:
    _require(context, CLIENT_ROLES | INTERNAL_ROLES)
    query = select(ERPConnection).where(ERPConnection.connection_id == connection_id)
    if context.role not in INTERNAL_ROLES:
        query = query.where(ERPConnection.tenant_id == context.tenant_id)
    connection = db.scalar(query)
    if connection is None:
        raise ApiError(404, "ERP_CONNECTION_NOT_FOUND", "Conexão ERP não encontrada.")
    if connection.status == "REVOKED":
        raise ApiError(409, "ERP_CONNECTION_REVOKED", "A conexão ERP foi revogada.")
    job = IntegrationSyncJob(connection_id=connection_id, tenant_id=connection.tenant_id, mode="READ_ONLY")
    db.add(job)
    connection.status = "SYNC_QUEUED"
    db.flush()
    _audit(db, request, context, "ERP_SYNC_REQUESTED", "ERP_CONNECTION", connection_id)
    db.commit()
    db.refresh(job)
    return job

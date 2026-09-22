import os

from cryptography.fernet import Fernet


def _inputs() -> dict:
    return {
        "base_date": "2026-01-15",
        "months": 3,
        "physical": {"units": 8, "area_equivalent_m2": 800},
        "revenue": {"total_vgv": 900000, "absorption_curve": [50, 30, 20]},
        "costs": {"land_total": 150000, "construction_total": 500000, "other_total": 30000},
        "funding": {"construction_percent": 40, "annual_rate": 12, "amortization_months": 3},
        "discount": {"annual_rate": 18},
    }


def test_viability_lifecycle(client, ids, auth_headers):
    headers = auth_headers(ids["client_user"], ids["client_tenant"])
    response = client.post(
        "/api/v1/viability/studies",
        headers=headers,
        json={
            "title": "Piloto residencial",
            "project_name": "Residencial Aurora",
            "base_date": "2026-01-15",
            "inputs": _inputs(),
        },
    )
    assert response.status_code == 201, response.text
    study = response.json()

    scenario_response = client.post(
        f"/api/v1/viability/studies/{study['study_id']}/scenarios",
        headers=headers,
        json={"scenario_key": "BASE", "name": "Cenário base", "overrides": {}},
    )
    assert scenario_response.status_code == 201, scenario_response.text

    calculation_response = client.post(
        f"/api/v1/viability/studies/{study['study_id']}/scenarios/BASE/calculate",
        headers=headers,
        json={},
    )
    assert calculation_response.status_code == 200, calculation_response.text
    calculation = calculation_response.json()
    assert calculation["outputs"]["engine_version"] == "m1-fcd-v1"
    assert len(calculation["flow"]) == 3

    sensitivity_response = client.post(
        f"/api/v1/viability/studies/{study['study_id']}/scenarios/BASE/sensitivity",
        headers=headers,
        json={"variable": "price", "shocks": [-0.1, 0, 0.1]},
    )
    assert sensitivity_response.status_code == 200, sensitivity_response.text
    sensitivity = sensitivity_response.json()
    assert len(sensitivity["results"]) == 3


def test_viability_isolation(client, ids, auth_headers):
    client_headers = auth_headers(ids["client_user"], ids["client_tenant"])
    foreign_headers = auth_headers(ids["foreign_user"], ids["foreign_tenant"])
    response = client.post(
        "/api/v1/viability/studies",
        headers=client_headers,
        json={"title": "Privado", "project_name": "Projeto Cliente", "base_date": "2026-01-15", "inputs": _inputs()},
    )
    study_id = response.json()["study_id"]
    denied = client.get(f"/api/v1/viability/studies/{study_id}", headers=foreign_headers)
    assert denied.status_code in {404, 405}


def test_erp_connection_requires_encryption_key(client, ids, auth_headers):
    os.environ.pop("FINTECH_ERP_ENCRYPTION_KEY", None)
    headers = auth_headers(ids["client_user"], ids["client_tenant"])
    response = client.post(
        "/api/v1/viability/erp-connections",
        headers=headers,
        json={"provider": "SIENGE", "external_tenant": "demo", "base_url": "https://erp.example.test", "scopes": ["READ_ONLY"], "secret": "secret-value"},
    )
    assert response.status_code == 503


def test_erp_sync_review_and_apply(client, ids, auth_headers, monkeypatch):
    from app.config import get_settings
    from app.erp_adapters import ERPSyncResult, ERPResourceEvidence

    monkeypatch.setenv("FINTECH_ERP_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    get_settings.cache_clear()
    headers = auth_headers(ids["client_user"], ids["client_tenant"])
    study_response = client.post(
        "/api/v1/viability/studies",
        headers=headers,
        json={
            "title": "ERP study",
            "project_name": "Residencial ERP",
            "base_date": "2026-01-15",
            "inputs": _inputs(),
        },
    )
    assert study_response.status_code == 201, study_response.text
    study_id = study_response.json()["study_id"]

    connection_response = client.post(
        "/api/v1/viability/erp-connections",
        headers=headers,
        json={
            "provider": "SIENGE",
            "external_tenant": "tenant-demo",
            "base_url": "https://erp.example.test",
            "scopes": ["READ_ONLY"],
            "resource_map": {"projects": "/projects"},
            "secret": "api-user:api-password",
        },
    )
    assert connection_response.status_code == 201, connection_response.text
    connection_id = connection_response.json()["connection_id"]

    class FakeAdapter:
        def __init__(self, **kwargs):
            assert kwargs["provider"] == "SIENGE"
            assert kwargs["resource_map"] == {"projects": "/projects"}

        def sync(self, **kwargs):
            return ERPSyncResult(
                provider="SIENGE",
                external_tenant="tenant-demo",
                records_seen=1,
                resources=(ERPResourceEvidence("projects", "/projects", 1, "sha256:test", "2026-01-15T00:00:00+00:00"),),
                cursor=None,
                warnings=(),
                normalized_inputs={"physical": {"units": 12}},
            )

    monkeypatch.setattr("app.routers.viability.ReadOnlyERPAdapter", FakeAdapter)
    sync_response = client.post(
        f"/api/v1/viability/erp-connections/{connection_id}/sync/run?study_id={study_id}",
        headers=headers,
    )
    assert sync_response.status_code == 200, sync_response.text
    assert sync_response.json()["status"] == "SUCCEEDED"
    sync_job_id = sync_response.json()["sync_job_id"]

    denied_apply = client.post(
        f"/api/v1/viability/erp-sync-jobs/{sync_job_id}/apply",
        headers=headers,
        json={"confirm": False},
    )
    assert denied_apply.status_code == 422

    apply_response = client.post(
        f"/api/v1/viability/erp-sync-jobs/{sync_job_id}/apply",
        headers=headers,
        json={"confirm": True},
    )
    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["inputs_json"]["physical"]["units"] == 12

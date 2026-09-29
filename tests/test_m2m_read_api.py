from tests.m2m_test_support import build_claims, make_client, m2m_headers


def test_m2m_health_returns_safe_versioned_envelope(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)

    response = client.get(
        "/api/v1/m2m/health",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["tenant_id"] == ids["platform_tenant"]
    assert body["capability"] == "fintech.health.read"
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["contract_version"] == "m2m-r1"
    assert body["data"]["database"] == "reachable"
    assert body["data"]["release_sha"] == "test-release-sha"
    assert response.headers["X-Execution-ID"] == "90000000-0000-0000-0000-000000000013"


def test_m2m_runtime_does_not_expose_secrets(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)

    response = client.get(
        "/api/v1/m2m/runtime",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 200
    body_text = response.text
    assert "test-only-secret" not in body_text
    assert "FINTECH_DATABASE_URL" not in body_text
    data = response.json()["data"]
    assert data["contract_version"] == "m2m-r1"
    assert data["dependencies"] == {"database": "reachable"}


def test_m2m_capability_catalog_is_exactly_read_only_r1(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)

    response = client.get(
        "/api/v1/m2m/capabilities",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 200
    items = response.json()["data"]["capabilities"]
    assert {item["scope"] for item in items} == {
        "fintech.health.read",
        "fintech.runtime.read",
        "fintech.capabilities.read",
        "fintech.audit.read",
    }
    assert all(item["method"] == "GET" for item in items)
    assert all(item["write"] is False for item in items)
    assert not any("superadmin" in item["scope"] or item["scope"] == "fintech.all" for item in items)


def test_m2m_validation_errors_use_canonical_envelope(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)

    response = client.get(
        "/api/v1/m2m/audit/events?limit=not-an-int",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "M2M_VALIDATION_ERROR"


def test_m2m_unhandled_error_is_canonical_and_does_not_leak(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)

    def explode(*args, **kwargs):
        raise RuntimeError("database-password-should-never-leak")

    monkeypatch.setattr("app.routers.m2m._service.health", explode)
    response = client.get(
        "/api/v1/m2m/health",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "M2M_INTERNAL_ERROR"
    assert "database-password-should-never-leak" not in response.text

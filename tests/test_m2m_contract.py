from app.m2m.scopes import R1_CAPABILITIES
from tests.m2m_test_support import build_claims, make_client, m2m_headers


def test_m2m_r1_has_no_write_routes():
    assert R1_CAPABILITIES
    assert all(item.method == "GET" for item in R1_CAPABILITIES)
    assert all(item.write is False for item in R1_CAPABILITIES)
    assert not any("/commands/" in item.path for item in R1_CAPABILITIES)


def test_m2m_response_echoes_canonical_ids(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)
    response = client.get(
        "/api/v1/m2m/health",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    body = response.json()
    assert body["request_id"] == "90000000-0000-0000-0000-000000000011"
    assert body["correlation_id"] == "90000000-0000-0000-0000-000000000012"
    assert body["execution_id"] == "90000000-0000-0000-0000-000000000013"


def test_m2m_invalid_request_id_fails_closed(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)
    headers = m2m_headers(
        tenant_id=ids["platform_tenant"],
        organization_id=ids["platform_org"],
    )
    headers["X-Request-ID"] = "not-a-uuid"

    response = client.get("/api/v1/m2m/health", headers=headers)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "M2M_VALIDATION_ERROR"
    assert body["request_id"] != "not-a-uuid"
    assert body["execution_id"] == "90000000-0000-0000-0000-000000000013"

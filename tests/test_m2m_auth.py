from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.m2m.auth import OidcIntrospectionM2MTokenValidator
from app.m2m.errors import M2MApiError
from tests.m2m_test_support import (
    build_claims,
    configure_m2m_env,
    make_client,
    m2m_headers,
    patch_introspection,
)


def test_m2m_route_absent_when_feature_flag_disabled(client):
    response = client.get("/api/v1/m2m/health")
    assert response.status_code == 404


def test_m2m_requires_bearer(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)
    headers = m2m_headers(
        tenant_id=ids["platform_tenant"],
        organization_id=ids["platform_org"],
    )
    headers.pop("Authorization")
    response = client.get("/api/v1/m2m/health", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "M2M_UNAUTHENTICATED"


def test_m2m_rejects_wrong_audience(monkeypatch, ids):
    claims = build_claims(
        tenant_scope=[ids["platform_tenant"]],
        audience="wrong-audience",
    )
    client = make_client(monkeypatch, claims)
    response = client.get(
        "/api/v1/m2m/health",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "M2M_UNAUTHENTICATED"


def test_m2m_rejects_wrong_environment(monkeypatch, ids):
    claims = build_claims(
        tenant_scope=[ids["platform_tenant"]],
        environment="production",
    )
    client = make_client(monkeypatch, claims)
    response = client.get(
        "/api/v1/m2m/health",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "M2M_UNAUTHENTICATED"


def test_m2m_rejects_token_lifetime_over_limit(monkeypatch, ids):
    claims = build_claims(
        tenant_scope=[ids["platform_tenant"]],
        lifetime_seconds=1800,
    )
    configure_m2m_env(monkeypatch)
    patch_introspection(monkeypatch, claims)
    settings = Settings()
    validator = OidcIntrospectionM2MTokenValidator(settings)

    with pytest.raises(M2MApiError) as captured:
        validator.validate("token-ok")

    assert captured.value.code == "M2M_UNAUTHENTICATED"

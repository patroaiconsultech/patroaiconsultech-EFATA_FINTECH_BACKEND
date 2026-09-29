from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEvent
from tests.m2m_test_support import build_claims, make_client, m2m_headers


def test_m2m_cross_tenant_request_is_denied(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)

    response = client.get(
        "/api/v1/m2m/health",
        headers=m2m_headers(
            tenant_id=ids["foreign_tenant"],
            organization_id=ids["foreign_org"],
        ),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "M2M_TENANT_DENIED"


def test_m2m_wrong_organization_is_denied_without_enumeration(monkeypatch, ids):
    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)

    response = client.get(
        "/api/v1/m2m/health",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["foreign_org"],
        ),
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "M2M_TENANT_DENIED"
    assert "não está autorizado" in body["error"]["message"]


def test_m2m_scope_denial_is_persisted_only_after_valid_tenant_context(monkeypatch, ids):
    claims = build_claims(
        tenant_scope=[ids["platform_tenant"]],
        capabilities=["fintech.health.read"],
    )
    client = make_client(monkeypatch, claims)

    response = client.get(
        "/api/v1/m2m/runtime",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "M2M_SCOPE_DENIED"

    with SessionLocal() as db:
        event = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == ids["platform_tenant"],
                AuditEvent.action == "M2M_REQUEST",
            )
            .order_by(AuditEvent.occurred_at.desc())
        )
        assert event is not None
        assert event.detail["decision"] == "deny"
        assert event.detail["error_code"] == "M2M_SCOPE_DENIED"
        assert event.detail["capability"] == "fintech.runtime.read"

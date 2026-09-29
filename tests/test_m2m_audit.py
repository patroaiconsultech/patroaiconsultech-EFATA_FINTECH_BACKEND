from datetime import datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEvent
from tests.m2m_test_support import build_claims, make_client, m2m_headers


def test_successful_m2m_request_persists_structured_audit(monkeypatch, ids):
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
        assert event.actor_id == "30000000-0000-0000-0000-000000000001"
        assert event.detail["service_id"] == "service:efata-platform"
        assert event.detail["client_id"] == "efata-mother-client"
        assert event.detail["credential_id"] == "40000000-0000-0000-0000-000000000001"
        assert event.detail["organization_id"] == ids["platform_org"]
        assert event.detail["capability"] == "fintech.health.read"
        assert event.detail["decision"] == "allow"
        assert event.detail["status"] == 200
        assert event.detail["write_allowed"] is False
        assert event.detail["execution_allowed"] is False
        assert "token-ok" not in str(event.detail)
        assert "test-only-secret" not in str(event.detail)


def test_m2m_audit_read_is_tenant_filtered_and_detail_is_not_exposed(monkeypatch, ids):
    with SessionLocal() as db:
        db.add_all(
            [
                AuditEvent(
                    tenant_id=ids["platform_tenant"],
                    actor_id=ids["analyst_user"],
                    action="PLATFORM_ONLY",
                    resource_type="TEST",
                    resource_id="platform-resource",
                    request_id="90000000-0000-0000-0000-000000000021",
                    correlation_id="90000000-0000-0000-0000-000000000022",
                    detail={"secret_business_field": "must-not-leak"},
                    occurred_at=datetime.now(timezone.utc),
                ),
                AuditEvent(
                    tenant_id=ids["foreign_tenant"],
                    actor_id=ids["foreign_user"],
                    action="FOREIGN_ONLY",
                    resource_type="TEST",
                    resource_id="foreign-resource",
                    request_id="90000000-0000-0000-0000-000000000023",
                    correlation_id="90000000-0000-0000-0000-000000000024",
                    detail={"secret_business_field": "foreign-secret"},
                    occurred_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()

    claims = build_claims(tenant_scope=[ids["platform_tenant"]])
    client = make_client(monkeypatch, claims)
    response = client.get(
        "/api/v1/m2m/audit/events?limit=100",
        headers=m2m_headers(
            tenant_id=ids["platform_tenant"],
            organization_id=ids["platform_org"],
        ),
    )
    assert response.status_code == 200
    body = response.json()
    items = body["data"]["items"]
    assert any(item["action"] == "PLATFORM_ONLY" for item in items)
    assert not any(item["action"] == "FOREIGN_ONLY" for item in items)
    assert "secret_business_field" not in response.text
    assert "foreign-secret" not in response.text

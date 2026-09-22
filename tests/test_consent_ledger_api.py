from datetime import datetime, timedelta, timezone


def test_consent_ledger_api_flow(client, ids, auth_headers):
    headers = auth_headers(ids["client_user"], ids["client_tenant"])
    response = client.post(
        "/api/v1/consent/grants",
        headers=headers,
        json={
            "subject_ref": "subject-hash-api-001",
            "purpose": "CREDIT_RISK_ANALYSIS",
            "scopes": ["transactions.read", "balances.read"],
            "recipient": "efata-risk-agent",
            "source_institution": "bank-adapter",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    consent_id = response.json()["consent_id"]

    access = client.post(
        f"/api/v1/consent/grants/{consent_id}/access",
        headers=headers,
        json={"purpose": "CREDIT_RISK_ANALYSIS", "scopes": ["transactions.read"]},
    )
    assert access.status_code == 200, access.text

    revoke = client.post(
        f"/api/v1/consent/grants/{consent_id}/revoke",
        headers=headers,
        json={"reason": "requested_by_subject"},
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "REVOKED"

    integrity = client.get(
        f"/api/v1/consent/integrity/{ids['client_tenant']}",
        headers=auth_headers(ids["analyst_user"], ids["platform_tenant"]),
    )
    assert integrity.status_code == 200, integrity.text
    assert integrity.json()["valid"] is True
    assert integrity.json()["event_count"] == 6


def test_consent_integrity_is_internal_only(client, ids, auth_headers):
    response = client.get(
        f"/api/v1/consent/integrity/{ids['client_tenant']}",
        headers=auth_headers(ids["client_user"], ids["client_tenant"]),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INTERNAL_ONLY"

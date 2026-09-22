from datetime import datetime, timezone


def commission_payload(ids, *, match_id="match-api-1", contract_id="contract-api-1"):
    return {
        "match_id": match_id,
        "beneficiary_tenant_id": ids["platform_tenant"],
        "trigger_event": "CONTACT_RELEASED",
        "base_amount": "5000000.00",
        "rate_bps": 75,
        "currency": "BRL",
        "contract_id": contract_id,
    }


def settlement_payload(ids, *, event_id="settlement-api-1", amount="38000.00", match_id="match-api-1", contract_id="contract-api-1"):
    return {
        "external_event_id": event_id,
        "beneficiary_tenant_id": ids["platform_tenant"],
        "amount": amount,
        "currency": "BRL",
        "settled_at": datetime.now(timezone.utc).isoformat(),
        "contract_id": contract_id,
        "match_id": match_id,
        "source": "BANK_API_TEST",
    }


def test_operator_can_manage_review_queue_and_outbox(client, ids, auth_headers):
    headers = auth_headers(ids["analyst_user"], ids["platform_tenant"])

    created = client.post(
        "/api/v1/reconciliation/persistent/commissions",
        json=commission_payload(ids),
        headers=headers,
    )
    assert created.status_code == 201
    commission_id = created.json()["commission_id"]

    for status in ("CONTRACT_PENDING", "TRIGGER_PENDING", "ELIGIBLE"):
        response = client.post(
            f"/api/v1/reconciliation/persistent/commissions/{commission_id}/transition",
            json={"status": status, "contract_id": "contract-api-1"},
            headers=headers,
        )
        assert response.status_code == 200, response.text

    settlement = client.post(
        "/api/v1/reconciliation/persistent/settlements",
        json=settlement_payload(ids),
        headers=headers,
    )
    assert settlement.status_code == 200
    assert settlement.json()["decision"] == "REVIEW_REQUIRED"
    assert settlement.json()["reason"] == "AMOUNT_VARIANCE"

    reviews = client.get("/api/v1/reconciliation/persistent/reviews", headers=headers)
    assert reviews.status_code == 200
    assert len(reviews.json()) == 1
    review_id = reviews.json()[0]["review_id"]

    claimed = client.post(
        "/api/v1/reconciliation/persistent/reviews/claim",
        json={},
        headers=headers,
    )
    assert claimed.status_code == 200
    assert claimed.json()[0]["status"] == "CLAIMED"

    resolved = client.post(
        f"/api/v1/reconciliation/persistent/reviews/{review_id}/resolve",
        json={
            "decision": "ACCEPT_VARIANCE",
            "notes": "Diferença validada pelo operador contra o aditivo.",
        },
        headers=headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["decision"] == "ACCEPT_VARIANCE"

    pending_outbox = client.post(
        "/api/v1/reconciliation/persistent/outbox/claim",
        headers=headers,
    )
    assert pending_outbox.status_code == 200
    assert len(pending_outbox.json()) == 1
    outbox_id = pending_outbox.json()[0]["outbox_id"]

    ack = client.post(
        f"/api/v1/reconciliation/persistent/outbox/{outbox_id}/ack",
        params={"published": "true"},
        headers=headers,
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "PUBLISHED"


def test_external_role_cannot_access_review_queue(client, ids, auth_headers):
    headers = auth_headers(ids["foreign_user"], ids["foreign_tenant"])
    response = client.get("/api/v1/reconciliation/persistent/reviews", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INTERNAL_ONLY"

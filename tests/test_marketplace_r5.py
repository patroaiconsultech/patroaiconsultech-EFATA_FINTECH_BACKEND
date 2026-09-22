from decimal import Decimal


def test_bilateral_marketplace_matching_and_commission(client, ids, auth_headers):
    borrower_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    funder_headers = auth_headers(ids["foreign_user"], ids["foreign_tenant"])
    analyst_headers = auth_headers(ids["analyst_user"], ids["platform_tenant"])

    borrower = client.post(
        "/api/v1/marketplace/borrower-profiles",
        headers=borrower_headers,
        json={
            "segment": "INCORPORADORA",
            "sectors": ["REAL_ESTATE"],
            "regions": ["SP"],
            "group_profile": {"employees": 120},
        },
    )
    assert borrower.status_code == 201
    borrower_profile_id = borrower.json()["borrower_profile_id"]

    provider = client.post(
        "/api/v1/marketplace/funding-providers",
        headers=funder_headers,
        json={
            "provider_type": "FUND",
            "legal_name": "Fundo Horizonte",
            "mandate_summary": "Crédito estruturado para real estate residencial.",
        },
    )
    assert provider.status_code == 201

    product = client.post(
        "/api/v1/marketplace/funding-products",
        headers=funder_headers,
        json={
            "name": "CRI Residencial SP",
            "product_type": "REAL_ESTATE",
            "min_ticket": "1000000",
            "max_ticket": "10000000",
            "min_term_months": 12,
            "max_term_months": 60,
            "allowed_collateral_types": ["RECEIVABLES"],
            "sectors": ["REAL_ESTATE"],
            "regions": ["SP"],
            "stage_requirements": ["STRUCTURED"],
            "indicative_terms": {"indexer": "IPCA"},
            "status": "ACTIVE",
        },
    )
    assert product.status_code == 201, product.text

    credit_request = client.post(
        "/api/v1/marketplace/credit-requests",
        headers=borrower_headers,
        json={
            "borrower_profile_id": borrower_profile_id,
            "title": "Residencial Aurora",
            "credit_type": "REAL_ESTATE",
            "requested_amount": "5000000",
            "term_months": 36,
            "grace_months": 6,
            "collateral_types": ["RECEIVABLES"],
            "sectors": ["REAL_ESTATE"],
            "regions": ["SP"],
            "project_stage": "STRUCTURED",
            "purpose": "Financiamento da construção e comercialização do projeto.",
            "consent_status": "GRANTED",
            "status": "SUBMITTED",
        },
    )
    assert credit_request.status_code == 201, credit_request.text
    credit_request_id = credit_request.json()["credit_request_id"]

    document = client.post(
        f"/api/v1/marketplace/credit-requests/{credit_request_id}/documents",
        headers=borrower_headers,
        json={"filename": "balanco.pdf", "document_type": "FINANCIAL_STATEMENTS", "checksum_sha256": "a" * 64},
    )
    assert document.status_code == 201, document.text
    assert document.json()["processing_status"] == "MOCK_ACCEPTED"
    documents = client.get(
        f"/api/v1/marketplace/credit-requests/{credit_request_id}/documents",
        headers=analyst_headers,
    )
    assert documents.status_code == 200
    assert len(documents.json()) == 1

    matches = client.post(
        f"/api/v1/marketplace/credit-requests/{credit_request_id}/matching",
        headers=analyst_headers,
    )
    assert matches.status_code == 201, matches.text
    match = matches.json()[0]
    assert match["eligible"] is True
    assert match["score"] == 100
    assert "ticket dentro da faixa" in match["reasons"]
    match_id = match["match_id"]

    risk_payload = {
        "credit_request_id": credit_request_id,
        "consent_status": "GRANTED",
        "requested_amount": "5000000",
        "currency": "BRL",
        "term_months": 36,
        "project_stage": "STRUCTURED",
        "purpose": "Financiamento da construção e comercialização do projeto.",
        "collateral_types": ["RECEIVABLES"],
        "sectors": ["REAL_ESTATE"],
        "regions": ["SP"],
        "document_types": ["FINANCIAL_STATEMENTS", "CORPORATE_DOCUMENTS"],
        "revenue_monthly": "1000000",
        "debt_service_monthly": "500000",
        "ebitda_annual": "1500000",
        "total_debt": "4000000",
        "collateral_value": "8000000",
        "financial_data_confidence": "HIGH",
    }
    simulation = client.post("/api/v1/risk/simulate", headers=analyst_headers, json=risk_payload)
    assert simulation.status_code == 200, simulation.text
    assert simulation.json()["decision"] == "ELIGIBLE_FOR_REVIEW"
    assert simulation.json()["risk_band"] == "LOW"
    assert simulation.json()["score"] == 100
    assessment = client.post(
        f"/api/v1/risk/credit-requests/{credit_request_id}/assessments",
        headers=analyst_headers,
        json=risk_payload,
    )
    assert assessment.status_code == 201, assessment.text
    assert assessment.json()["human_status"] == "PENDING"
    assessment_id = assessment.json()["assessment_id"]

    queue = client.get("/api/v1/risk/governance-queue", headers=analyst_headers)
    assert queue.status_code == 200
    queue_item = next(item for item in queue.json() if item["match_id"] == match_id)
    assert queue_item["risk_assessment"]["assessment_id"] == assessment_id
    assert queue_item["requires_human_decision"] is True

    review = client.post(
        f"/api/v1/risk/matches/{match_id}/governance-reviews",
        headers=analyst_headers,
        json={
            "assessment_id": assessment_id,
            "decision": "APPROVE_CONTACT",
            "reason": "Dossiê mínimo presente e indicadores dentro da política demo; liberar para revisão comercial.",
        },
    )
    assert review.status_code == 201, review.text
    assert review.json()["decision"] == "APPROVE_CONTACT"
    queue_after = client.get("/api/v1/risk/governance-queue", headers=analyst_headers)
    queue_after_item = next(item for item in queue_after.json() if item["match_id"] == match_id)
    assert queue_after_item["requires_human_decision"] is False
    assert queue_after_item["latest_review"]["decision"] == "APPROVE_CONTACT"
    assert queue_after_item["match_status"] == "APPROVED_TO_CONTACT"

    borrower_matches = client.get("/api/v1/marketplace/matches", headers=borrower_headers)
    assert borrower_matches.status_code == 200
    assert len(borrower_matches.json()) == 1

    updated = client.post(
        f"/api/v1/marketplace/matches/{match_id}/status",
        headers=analyst_headers,
        json={"status": "APPROVED_TO_CONTACT", "reason": "Aderência suficiente para contato inicial."},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "APPROVED_TO_CONTACT"

    commission = client.post(
        "/api/v1/marketplace/commission-events",
        headers=analyst_headers,
        json={
            "match_id": match_id,
            "beneficiary_tenant_id": ids["originator_tenant"],
            "event_type": "FORWARDED",
            "base_amount": "5000000",
            "rate_bps": 25,
        },
    )
    assert commission.status_code == 201, commission.text
    assert Decimal(commission.json()["estimated_amount"]) == Decimal("12500.0000")

    foreign_matches = client.get("/api/v1/marketplace/matches", headers=funder_headers)
    assert foreign_matches.status_code == 200
    assert len(foreign_matches.json()) == 1


def test_matching_requires_consent(client, ids, auth_headers):
    borrower_headers = auth_headers(ids["originator_user"], ids["originator_tenant"])
    analyst_headers = auth_headers(ids["analyst_user"], ids["platform_tenant"])
    profile = client.post(
        "/api/v1/marketplace/borrower-profiles",
        headers=borrower_headers,
        json={"segment": "OPERACIONAL", "sectors": ["LOGISTICS"], "regions": ["SP"]},
    ).json()
    request = client.post(
        "/api/v1/marketplace/credit-requests",
        headers=borrower_headers,
        json={
            "borrower_profile_id": profile["borrower_profile_id"],
            "title": "Capital de giro",
            "credit_type": "WORKING_CAPITAL",
            "requested_amount": "100000",
            "term_months": 24,
            "project_stage": "OPERATING",
            "purpose": "Capital de giro para expansão.",
            "consent_status": "PENDING",
        },
    ).json()
    response = client.post(
        f"/api/v1/marketplace/credit-requests/{request['credit_request_id']}/matching",
        headers=analyst_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_partner_can_register_referred_client_and_request(client, ids, auth_headers):
    partner_headers = auth_headers(ids["partner_user"], ids["partner_tenant"])
    partner = client.post(
        "/api/v1/marketplace/partners",
        headers=partner_headers,
        json={"partner_type": "ADVISOR", "focus_regions": ["SP"]},
    )
    assert partner.status_code == 201, partner.text
    profile = client.post(
        "/api/v1/marketplace/borrower-profiles",
        headers=partner_headers,
        json={
            "segment": "INCORPORADORA",
            "sectors": ["REAL_ESTATE"],
            "regions": ["SP"],
            "group_profile": {"legal_name": "Cliente Indicado"},
        },
    )
    assert profile.status_code == 201
    request = client.post(
        "/api/v1/marketplace/credit-requests",
        headers=partner_headers,
        json={
            "borrower_profile_id": profile.json()["borrower_profile_id"],
            "source_partner_tenant_id": ids["partner_tenant"],
            "title": "Demanda indicada",
            "credit_type": "REAL_ESTATE",
            "requested_amount": "2500000",
            "term_months": 36,
            "project_stage": "STRUCTURED",
            "purpose": "Demanda originada por parceiro.",
            "consent_status": "GRANTED",
        },
    )
    assert request.status_code == 201, request.text
    assert request.json()["source_partner_tenant_id"] == ids["partner_tenant"]


def test_risk_assessment_is_internal_only(client, ids, auth_headers):
    funder_headers = auth_headers(ids["foreign_user"], ids["foreign_tenant"])
    response = client.post(
        "/api/v1/risk/credit-requests/missing/assessments",
        headers=funder_headers,
        json={
            "requested_amount": "1000000",
            "term_months": 24,
            "project_stage": "OPERATING",
            "purpose": "Operação de teste.",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INTERNAL_ONLY"


def test_internal_agent_registry_is_restricted(client, ids, auth_headers):
    analyst_headers = auth_headers(ids["analyst_user"], ids["platform_tenant"])
    agents = client.get("/api/v1/marketplace/agents", headers=analyst_headers)
    assert agents.status_code == 200
    assert len(agents.json()) == 7
    assert {item["key"] for item in agents.json()} >= {"intake_data", "funding_match", "governance_compliance", "credit_risk"}
    assert all(item["human_review_required"] for item in agents.json())

    funder_headers = auth_headers(ids["foreign_user"], ids["foreign_tenant"])
    denied = client.get("/api/v1/marketplace/agents", headers=funder_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ROLE_NOT_ALLOWED"

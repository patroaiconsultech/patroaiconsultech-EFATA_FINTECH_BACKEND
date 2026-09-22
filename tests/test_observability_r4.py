def test_request_correlation_headers_are_emitted(client):
    response = client.get(
        "/api/v1/health/live",
        headers={
            "X-Request-ID": "req-r4",
            "X-Correlation-ID": "corr-r4",
        },
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-r4"
    assert response.headers["X-Correlation-ID"] == "corr-r4"
    assert float(response.headers["X-Duration-Ms"]) >= 0


def test_ready_exposes_baseline_modes(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["auth_provider"] == "mock"
    assert body["efata_mode"] == "mock"

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


SERVICE_PRINCIPAL_ID = "30000000-0000-0000-0000-000000000001"
CLIENT_ID = "efata-mother-client"
INTROSPECTION_CLIENT_ID = "fintech-introspector"
INTROSPECTION_SECRET = "test-only-secret"
JTI = "40000000-0000-0000-0000-000000000001"

ALL_R1_CAPABILITIES = [
    "fintech.health.read",
    "fintech.runtime.read",
    "fintech.capabilities.read",
    "fintech.audit.read",
]


class FakeIntrospectionResponse:
    def __init__(self, claims: dict, status_code: int = 200):
        self._claims = claims
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"upstream status {self.status_code}")

    def json(self):
        return self._claims


def configure_m2m_env(monkeypatch):
    monkeypatch.setenv("FINTECH_M2M_ENABLED", "true")
    monkeypatch.setenv("FINTECH_M2M_AUTH_MODE", "oidc_introspection")
    monkeypatch.setenv("FINTECH_M2M_INTROSPECTION_ENDPOINT", "https://idp.test/introspect")
    monkeypatch.setenv("FINTECH_M2M_INTROSPECTION_CLIENT_ID", INTROSPECTION_CLIENT_ID)
    monkeypatch.setenv("FINTECH_M2M_INTROSPECTION_CLIENT_SECRET", INTROSPECTION_SECRET)
    monkeypatch.setenv("FINTECH_M2M_ISSUER", "efata-mother")
    monkeypatch.setenv("FINTECH_M2M_AUDIENCE", "efata-fintech")
    monkeypatch.setenv("FINTECH_M2M_ALLOWED_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("FINTECH_M2M_SERVICE_PRINCIPAL_ID", SERVICE_PRINCIPAL_ID)
    monkeypatch.setenv("FINTECH_M2M_MAX_TOKEN_LIFETIME_SECONDS", "900")
    monkeypatch.setenv("FINTECH_RELEASE_SHA", "test-release-sha")
    monkeypatch.setenv("FINTECH_RELEASE_VERSION", "test-release-version")
    get_settings.cache_clear()


def build_claims(
    *,
    tenant_scope: list[str],
    capabilities: list[str] | None = None,
    active: bool = True,
    issuer: str = "efata-mother",
    audience: str = "efata-fintech",
    environment: str = "test",
    client_id: str = CLIENT_ID,
    subject: str = "service:efata-platform",
    jti: str = JTI,
    lifetime_seconds: int = 600,
):
    now = datetime.now(timezone.utc).timestamp()
    return {
        "active": active,
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "env": environment,
        "client_id": client_id,
        "jti": jti,
        "tenant_scope": tenant_scope,
        "capabilities": capabilities or list(ALL_R1_CAPABILITIES),
        "iat": now - 1,
        "exp": now + lifetime_seconds,
    }


def patch_introspection(monkeypatch, claims: dict):
    def fake_post(url, *, data, auth, timeout):
        assert url == "https://idp.test/introspect"
        assert data == {"token": "token-ok"}
        assert auth == (INTROSPECTION_CLIENT_ID, INTROSPECTION_SECRET)
        assert timeout == 5.0
        return FakeIntrospectionResponse(claims)

    monkeypatch.setattr("app.m2m.auth.httpx.post", fake_post)


def make_client(monkeypatch, claims: dict) -> TestClient:
    configure_m2m_env(monkeypatch)
    patch_introspection(monkeypatch, claims)
    return TestClient(create_app())


def m2m_headers(*, tenant_id: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer token-ok",
        "X-Tenant-ID": tenant_id,
        "X-Organization-ID": organization_id,
        "X-Request-ID": "90000000-0000-0000-0000-000000000011",
        "X-Correlation-ID": "90000000-0000-0000-0000-000000000012",
        "X-Execution-ID": "90000000-0000-0000-0000-000000000013",
    }

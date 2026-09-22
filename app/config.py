from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINTECH_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "Efatà Fintech"
    app_env: Literal["local", "test", "development", "staging", "production"] = "local"
    database_url: str = "sqlite:///./fintech.db"
    premium_slice_enabled: bool = True

    # Authentication boundary. Controllers remain provider-agnostic.
    auth_provider: Literal["mock", "oidc"] = "mock"
    oidc_introspection_endpoint: str | None = None
    oidc_introspection_client_id: str | None = None
    oidc_introspection_client_secret: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_user_claim: str = "sub"
    oidc_tenant_claim: str = "tenant_id"
    oidc_roles_claim: str = "roles"
    oidc_http_timeout_seconds: float = 5.0
    cors_allowed_origins: str = "http://localhost:5173"

    # ERP credentials are encrypted before persistence; production must provide a Fernet key
    # through a sealed secret or external KMS-backed secret manager.
    erp_encryption_key: str | None = None
    erp_allowed_hosts: str = ""
    erp_http_timeout_seconds: float = 10.0
    erp_max_records_per_resource: int = 5000

    # Domain integration remains mock-only until the external platform contract
    # is approved for a real environment.
    efata_mode: Literal["mock", "sandbox", "staging", "production"] = "mock"
    efata_contract_version: str = "r11.2-efata-v2-preview"
    platform_tenant_id: str | None = "00000000-0000-0000-0000-000000000003"

    # Efatà Platform V2 compatibility bridge. This is infrastructure-only in R11.2:
    # no business route calls it and network access is fail-closed by default.
    efata_platform_bridge_enabled: bool = False
    efata_platform_base_url: str | None = None
    efata_platform_access_token: str | None = None
    efata_platform_api_prefix: str = "/api/v2"
    efata_platform_default_agent: str = "Josué"
    efata_platform_timeout_seconds: float = 15.0
    efata_platform_sse_max_event_bytes: int = 1_048_576
    efata_platform_sse_max_events: int = 10_000

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

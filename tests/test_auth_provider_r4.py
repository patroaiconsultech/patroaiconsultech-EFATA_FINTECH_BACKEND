from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.auth_provider import AuthIdentity, MockAuthProvider, OidcProvider
from app.config import Settings
from app.db import SessionLocal
from app.errors import ApiError
from app.models import Membership
from app.security import SecurityContextFactory


class FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers
        self.state = SimpleNamespace()


class FakeValidator:
    def validate(self, token: str) -> AuthIdentity:
        assert token == "token-ok"
        return AuthIdentity(
            user_id="20000000-0000-0000-0000-000000000001",
            tenant_id="00000000-0000-0000-0000-000000000001",
            asserted_roles=("PLATFORM_ADMIN",),
            external_subject="external-subject",
            provider="oidc",
        )


def test_mock_auth_is_blocked_outside_local_and_test():
    provider = MockAuthProvider(
        Settings(
            app_env="staging",
            auth_provider="mock",
            database_url="sqlite://",
        )
    )
    with pytest.raises(ApiError) as captured:
        provider.authenticate(
            FakeRequest(
                {
                    "X-User-ID": "user",
                    "X-Tenant-ID": "tenant",
                }
            )
        )
    assert captured.value.status_code == 503
    assert captured.value.code == "MOCK_AUTH_DISABLED"


def test_oidc_provider_requires_bearer():
    provider = OidcProvider(FakeValidator())
    with pytest.raises(ApiError) as captured:
        provider.authenticate(FakeRequest({}))
    assert captured.value.code == "BEARER_TOKEN_REQUIRED"


def test_security_context_uses_provisioned_membership_role():
    identity = FakeValidator().validate("token-ok")
    with SessionLocal() as db:
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == identity.user_id,
                Membership.tenant_id == identity.tenant_id,
            )
        )
        assert membership is not None
        assert membership.role == "ORIGINATOR_ADMIN"

        context = SecurityContextFactory().create(
            identity=identity,
            db=db,
        )

    # The token asserted PLATFORM_ADMIN but effective role stays local membership.
    assert context.role == "ORIGINATOR_ADMIN"
    assert context.auth_provider == "oidc"

from __future__ import annotations

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Membership, Organization, Tenant, User

PLATFORM_ORG_ID = "10000000-0000-0000-0000-000000000003"
PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000003"
ANALYST_USER_ID = "20000000-0000-0000-0000-000000000003"
ANALYST_MEMBERSHIP_ID = "30000000-0000-0000-0000-000000000003"

EXPECTED_APP_ENVS = {"local", "test", "development", "staging"}
EXPECTED_AUTH_PROVIDER = "mock"


def _ensure_exact(obj, *, entity: str, expected: dict[str, object]) -> None:
    mismatches = []
    for field, expected_value in expected.items():
        actual_value = getattr(obj, field)
        if actual_value != expected_value:
            mismatches.append(
                f"{field}: actual={actual_value!r}, expected={expected_value!r}"
            )
    if mismatches:
        raise RuntimeError(
            f"{entity} already exists with incompatible data: " + "; ".join(mismatches)
        )


def main() -> None:
    settings = get_settings()

    if settings.app_env not in EXPECTED_APP_ENVS:
        raise RuntimeError(
            f"Refusing demo principal bootstrap in FINTECH_APP_ENV={settings.app_env!r}"
        )

    if settings.auth_provider != EXPECTED_AUTH_PROVIDER:
        raise RuntimeError(
            "Refusing demo principal bootstrap unless FINTECH_AUTH_PROVIDER='mock'"
        )

    with SessionLocal() as db:
        try:
            organization = db.scalar(
                select(Organization).where(
                    Organization.organization_id == PLATFORM_ORG_ID
                )
            )
            if organization is None:
                organization = Organization(
                    organization_id=PLATFORM_ORG_ID,
                    legal_name="Plataforma Demo",
                    organization_type="PLATFORM_OPERATOR",
                    status="ACTIVE",
                )
                db.add(organization)
                db.flush()
                print(f"BOOTSTRAP created organization={PLATFORM_ORG_ID}")
            else:
                _ensure_exact(
                    organization,
                    entity="Organization",
                    expected={
                        "legal_name": "Plataforma Demo",
                        "organization_type": "PLATFORM_OPERATOR",
                        "status": "ACTIVE",
                    },
                )
                print(f"BOOTSTRAP organization already valid={PLATFORM_ORG_ID}")

            tenant = db.scalar(
                select(Tenant).where(Tenant.tenant_id == PLATFORM_TENANT_ID)
            )
            if tenant is None:
                tenant = Tenant(
                    tenant_id=PLATFORM_TENANT_ID,
                    organization_id=PLATFORM_ORG_ID,
                    tenant_type="PLATFORM_OPERATOR",
                    slug="platform-demo",
                    status="ACTIVE",
                )
                db.add(tenant)
                db.flush()
                print(f"BOOTSTRAP created tenant={PLATFORM_TENANT_ID}")
            else:
                _ensure_exact(
                    tenant,
                    entity="Tenant",
                    expected={
                        "organization_id": PLATFORM_ORG_ID,
                        "tenant_type": "PLATFORM_OPERATOR",
                        "slug": "platform-demo",
                        "status": "ACTIVE",
                    },
                )
                print(f"BOOTSTRAP tenant already valid={PLATFORM_TENANT_ID}")

            user = db.scalar(
                select(User).where(User.user_id == ANALYST_USER_ID)
            )
            if user is None:
                user = User(
                    user_id=ANALYST_USER_ID,
                    email="analyst@example.test",
                    display_name="Analista Demo",
                    status="ACTIVE",
                )
                db.add(user)
                db.flush()
                print(f"BOOTSTRAP created user={ANALYST_USER_ID}")
            else:
                _ensure_exact(
                    user,
                    entity="User",
                    expected={
                        "email": "analyst@example.test",
                        "display_name": "Analista Demo",
                        "status": "ACTIVE",
                    },
                )
                print(f"BOOTSTRAP user already valid={ANALYST_USER_ID}")

            membership = db.scalar(
                select(Membership).where(
                    Membership.user_id == ANALYST_USER_ID,
                    Membership.tenant_id == PLATFORM_TENANT_ID,
                )
            )
            if membership is None:
                membership = Membership(
                    membership_id=ANALYST_MEMBERSHIP_ID,
                    user_id=ANALYST_USER_ID,
                    tenant_id=PLATFORM_TENANT_ID,
                    role="ANALYST",
                    status="ACTIVE",
                )
                db.add(membership)
                db.flush()
                print(
                    "BOOTSTRAP created membership="
                    f"{ANALYST_MEMBERSHIP_ID} role=ANALYST"
                )
            else:
                _ensure_exact(
                    membership,
                    entity="Membership",
                    expected={
                        "user_id": ANALYST_USER_ID,
                        "tenant_id": PLATFORM_TENANT_ID,
                        "role": "ANALYST",
                        "status": "ACTIVE",
                    },
                )
                print(
                    "BOOTSTRAP membership already valid="
                    f"{membership.membership_id} role={membership.role}"
                )

            db.commit()
        except Exception:
            db.rollback()
            raise

    print("BOOTSTRAP_DEMO_PRINCIPAL_OK")


if __name__ == "__main__":
    main()

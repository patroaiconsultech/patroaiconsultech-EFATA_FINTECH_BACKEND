import os
os.environ.setdefault("FINTECH_APP_ENV", "test")
os.environ.setdefault("FINTECH_DATABASE_URL", "sqlite://")
os.environ.setdefault("FINTECH_PREMIUM_SLICE_ENABLED", "true")
os.environ.setdefault("FINTECH_AUTH_PROVIDER", "mock")
os.environ.setdefault(
    "FINTECH_PLATFORM_TENANT_ID",
    "00000000-0000-0000-0000-000000000003",
)

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
get_settings.cache_clear()

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Membership, Organization, Tenant, User


IDS = {
    "originator_org": "10000000-0000-0000-0000-000000000001",
    "originator_tenant": "00000000-0000-0000-0000-000000000001",
    "originator_user": "20000000-0000-0000-0000-000000000001",
    "client_org": "10000000-0000-0000-0000-000000000002",
    "client_tenant": "00000000-0000-0000-0000-000000000002",
    "client_user": "20000000-0000-0000-0000-000000000002",
    "platform_org": "10000000-0000-0000-0000-000000000003",
    "platform_tenant": "00000000-0000-0000-0000-000000000003",
    "analyst_user": "20000000-0000-0000-0000-000000000003",
    "foreign_org": "10000000-0000-0000-0000-000000000004",
    "foreign_tenant": "00000000-0000-0000-0000-000000000004",
    "foreign_user": "20000000-0000-0000-0000-000000000004",
    "partner_org": "10000000-0000-0000-0000-000000000005",
    "partner_tenant": "00000000-0000-0000-0000-000000000005",
    "partner_user": "20000000-0000-0000-0000-000000000005",
}


def seed() -> None:
    with SessionLocal() as db:
        orgs = [
            Organization(organization_id=IDS["originator_org"], legal_name="Originadora", organization_type="ORIGINATOR"),
            Organization(organization_id=IDS["client_org"], legal_name="Cliente", organization_type="CAPITAL_SEEKER"),
            Organization(organization_id=IDS["platform_org"], legal_name="Plataforma", organization_type="PLATFORM_OPERATOR"),
            Organization(organization_id=IDS["foreign_org"], legal_name="Terceiro", organization_type="INVESTOR"),
            Organization(organization_id=IDS["partner_org"], legal_name="Parceiro", organization_type="PARTNER"),
        ]
        tenants = [
            Tenant(tenant_id=IDS["originator_tenant"], organization_id=IDS["originator_org"], tenant_type="ORIGINATOR", slug="originator"),
            Tenant(tenant_id=IDS["client_tenant"], organization_id=IDS["client_org"], tenant_type="CAPITAL_SEEKER", slug="client"),
            Tenant(tenant_id=IDS["platform_tenant"], organization_id=IDS["platform_org"], tenant_type="PLATFORM_OPERATOR", slug="platform"),
            Tenant(tenant_id=IDS["foreign_tenant"], organization_id=IDS["foreign_org"], tenant_type="INVESTOR", slug="foreign"),
            Tenant(tenant_id=IDS["partner_tenant"], organization_id=IDS["partner_org"], tenant_type="PARTNER", slug="partner"),
        ]
        users = [
            User(user_id=IDS["originator_user"], email="originator@test.local", display_name="Originador"),
            User(user_id=IDS["client_user"], email="client@test.local", display_name="Cliente"),
            User(user_id=IDS["analyst_user"], email="analyst@test.local", display_name="Analista"),
            User(user_id=IDS["foreign_user"], email="foreign@test.local", display_name="Terceiro"),
            User(user_id=IDS["partner_user"], email="partner@test.local", display_name="Parceiro"),
        ]
        memberships = [
            Membership(user_id=IDS["originator_user"], tenant_id=IDS["originator_tenant"], role="ORIGINATOR_ADMIN"),
            Membership(user_id=IDS["client_user"], tenant_id=IDS["client_tenant"], role="CLIENT_ADMIN"),
            Membership(user_id=IDS["analyst_user"], tenant_id=IDS["platform_tenant"], role="ANALYST"),
            Membership(user_id=IDS["foreign_user"], tenant_id=IDS["foreign_tenant"], role="INVESTOR_ANALYST"),
            Membership(user_id=IDS["partner_user"], tenant_id=IDS["partner_tenant"], role="PARTNER_ADMIN"),
        ]
        # Flush in explicit FK dependency order. The ORM models intentionally
        # do not declare relationship() objects, so relying on one mixed
        # add_all()/flush can produce a Membership INSERT before its User on
        # PostgreSQL. SQLite previously masked this because FK enforcement is
        # not equivalent in the local test setup.
        db.add_all(orgs)
        db.flush()

        db.add_all(users)
        db.flush()

        db.add_all(tenants)
        db.flush()

        db.add_all(memberships)
        db.commit()


def _truncate_postgres_test_data() -> None:
    """Reset rows without destroying the Alembic-managed PostgreSQL schema.

    The PostgreSQL proof gate migrates the database first. Dropping Base
    metadata inside pytest would destroy that migrated schema while leaving
    Alembic's version table at head, invalidating the later downgrade proof.
    """
    table_names = [
        engine.dialect.identifier_preparer.quote(table.name)
        for table in Base.metadata.sorted_tables
    ]
    if not table_names:
        return

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE TABLE "
            + ", ".join(table_names)
            + " RESTART IDENTITY CASCADE"
        )


@pytest.fixture(autouse=True)
def reset_database():
    if engine.dialect.name == "postgresql":
        # Preserve the exact schema created by Alembic; isolate tests by rows.
        _truncate_postgres_test_data()
        seed()
        yield
        _truncate_postgres_test_data()
        return

    # Local SQLite regression keeps its historical isolated-schema behavior.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def ids():
    return IDS


def headers(user: str, tenant: str) -> dict[str, str]:
    return {
        "X-User-ID": user,
        "X-Tenant-ID": tenant,
        "X-Request-ID": "90000000-0000-0000-0000-000000000001",
        "X-Correlation-ID": "90000000-0000-0000-0000-000000000001",
    }


@pytest.fixture
def auth_headers():
    return headers

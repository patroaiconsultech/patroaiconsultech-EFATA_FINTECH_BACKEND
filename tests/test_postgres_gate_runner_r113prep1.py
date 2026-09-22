from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "postgres_gate.py"
SPEC = importlib.util.spec_from_file_location("postgres_gate", SCRIPT)
assert SPEC and SPEC.loader
postgres_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = postgres_gate
SPEC.loader.exec_module(postgres_gate)


def test_sanitizes_database_password():
    safe = postgres_gate.sanitize_database_url(
        "postgresql+psycopg://fintech:topsecret@localhost:5432/fintech_ci"
    )
    assert "topsecret" not in safe
    assert "***" in safe


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5432/fintech_ci",
        "postgresql+psycopg://u:p@localhost:5432/fintech_test",
        "postgresql+psycopg://u:p@localhost:5432/sandbox_fintech",
        "postgresql+psycopg://u:p@localhost:5432/fintech_ephemeral",
    ],
)
def test_accepts_dedicated_test_database_names(url):
    parsed = postgres_gate.assert_dedicated_test_database(
        url,
        confirmation=postgres_gate.DESTRUCTIVE_CONFIRM_VALUE,
    )
    assert parsed.drivername.startswith("postgresql")


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///fintech.db",
        "postgresql+psycopg://u:p@localhost:5432/fintech",
        "postgresql+psycopg://u:p@localhost:5432/production",
        "",
    ],
)
def test_rejects_non_dedicated_or_non_postgres_database(url):
    with pytest.raises(RuntimeError):
        postgres_gate.assert_dedicated_test_database(
            url,
            confirmation=postgres_gate.DESTRUCTIVE_CONFIRM_VALUE,
        )


def test_requires_explicit_destructive_confirmation():
    with pytest.raises(RuntimeError) as captured:
        postgres_gate.assert_dedicated_test_database(
            "postgresql+psycopg://u:p@localhost:5432/fintech_ci",
            confirmation=None,
        )
    assert "POSTGRES_GATE_DESTRUCTIVE_CONFIRMATION_REQUIRED" in str(captured.value)


def test_allowed_host_accepts_expected_target():
    parsed = postgres_gate.assert_dedicated_test_database(
        "postgresql+psycopg://u:p@localhost:5432/fintech_ci",
        confirmation=postgres_gate.DESTRUCTIVE_CONFIRM_VALUE,
        allowed_hosts_raw="localhost,127.0.0.1",
    )
    assert parsed.host == "localhost"


def test_allowed_host_rejects_unexpected_target():
    with pytest.raises(RuntimeError) as captured:
        postgres_gate.assert_dedicated_test_database(
            "postgresql+psycopg://u:p@db.example.net:5432/fintech_ci",
            confirmation=postgres_gate.DESTRUCTIVE_CONFIRM_VALUE,
            allowed_hosts_raw="localhost,127.0.0.1",
        )
    assert "POSTGRES_GATE_HOST_NOT_ALLOWED" in str(captured.value)

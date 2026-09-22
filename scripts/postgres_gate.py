from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url


SAFE_DATABASE_MARKERS = ("test", "testing", "ci", "sandbox", "ephemeral")
DESTRUCTIVE_CONFIRM_ENV = "FINTECH_POSTGRES_GATE_CONFIRM"
DESTRUCTIVE_CONFIRM_VALUE = "I_UNDERSTAND_THIS_DATABASE_WILL_BE_DOWNGRADED"
ALLOWED_HOSTS_ENV = "FINTECH_POSTGRES_GATE_ALLOWED_HOSTS"


@dataclass
class StepResult:
    name: str
    status: str
    returncode: int
    duration_ms: float
    stdout_tail: str = ""
    stderr_tail: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "DESTRUCTIVE TEST DATABASE ONLY. Reproducible PostgreSQL evidence "
            "gate for Efatà Fintech. NEVER run against shared/staging/production."
        ),
        epilog=(
            "Requires FINTECH_POSTGRES_GATE_CONFIRM="
            "I_UNDERSTAND_THIS_DATABASE_WILL_BE_DOWNGRADED. "
            "Optional FINTECH_POSTGRES_GATE_ALLOWED_HOSTS restricts target hosts."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("FINTECH_DATABASE_URL", ""),
        help="Dedicated PostgreSQL test/CI database URL.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("postgres_gate_report.json"),
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
    )
    return parser.parse_args()


def sanitize_database_url(raw: str) -> str:
    url = make_url(raw)
    return url.render_as_string(hide_password=True)


def assert_dedicated_test_database(
    raw: str,
    *,
    confirmation: str | None = None,
    allowed_hosts_raw: str | None = None,
) -> URL:
    if not raw:
        raise RuntimeError("POSTGRES_DATABASE_URL_REQUIRED")

    if confirmation != DESTRUCTIVE_CONFIRM_VALUE:
        raise RuntimeError(
            "POSTGRES_GATE_DESTRUCTIVE_CONFIRMATION_REQUIRED "
            f"({DESTRUCTIVE_CONFIRM_ENV}={DESTRUCTIVE_CONFIRM_VALUE})"
        )

    url = make_url(raw)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("POSTGRES_DATABASE_REQUIRED")

    database = (url.database or "").lower()
    if not database or not any(marker in database for marker in SAFE_DATABASE_MARKERS):
        raise RuntimeError(
            "POSTGRES_GATE_REQUIRES_DEDICATED_TEST_DATABASE "
            "(database name must contain test/testing/ci/sandbox/ephemeral)"
        )

    if allowed_hosts_raw:
        allowed_hosts = {
            host.strip().lower()
            for host in allowed_hosts_raw.split(",")
            if host.strip()
        }
        target_host = (url.host or "").lower()
        if not allowed_hosts:
            raise RuntimeError("POSTGRES_GATE_ALLOWED_HOSTS_EMPTY")
        if target_host not in allowed_hosts:
            raise RuntimeError(
                f"POSTGRES_GATE_HOST_NOT_ALLOWED target={target_host!r}"
            )

    return url


def run_step(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int = 300,
) -> StepResult:
    started = perf_counter()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        duration_ms = round((perf_counter() - started) * 1000, 3)
        return StepResult(
            name=name,
            status="PASS" if proc.returncode == 0 else "FAIL",
            returncode=proc.returncode,
            duration_ms=duration_ms,
            stdout_tail=proc.stdout[-5000:],
            stderr_tail=proc.stderr[-5000:],
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((perf_counter() - started) * 1000, 3)
        return StepResult(
            name=name,
            status="FAIL",
            returncode=124,
            duration_ms=duration_ms,
            stdout_tail=(exc.stdout or "")[-5000:] if isinstance(exc.stdout, str) else "",
            stderr_tail="TIMEOUT",
        )


def postgres_identity(raw: str) -> dict[str, Any]:
    engine = create_engine(raw, future=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "select version(), current_database(), current_user, "
                    "current_setting('server_version_num')"
                )
            ).one()
            return {
                "version": row[0],
                "database": row[1],
                "current_user": row[2],
                "server_version_num": row[3],
            }
    finally:
        engine.dispose()


def schema_inventory(raw: str) -> dict[str, Any]:
    engine = create_engine(raw, future=True)
    try:
        inspector = inspect(engine)
        tables = sorted(inspector.get_table_names())
        return {
            "table_count": len(tables),
            "tables": tables,
        }
    finally:
        engine.dispose()


def main() -> int:
    args = parse_args()
    backend_root = Path(__file__).resolve().parents[1]
    report_path = args.report.resolve()

    report: dict[str, Any] = {
        "schema_version": "EFATA-FINTECH-POSTGRES-GATE-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_url": None,
        "postgres": None,
        "steps": [],
        "final_status": "FAIL",
    }

    try:
        confirmation = os.getenv(DESTRUCTIVE_CONFIRM_ENV)
        allowed_hosts_raw = os.getenv(ALLOWED_HOSTS_ENV)
        assert_dedicated_test_database(
            args.database_url,
            confirmation=confirmation,
            allowed_hosts_raw=allowed_hosts_raw,
        )
        report["safety"] = {
            "destructive_test_database_only": True,
            "confirmation_required": True,
            "confirmation_value_recorded": False,
            "allowed_hosts_enforced": bool(allowed_hosts_raw),
            "allowed_hosts": (
                sorted(
                    host.strip().lower()
                    for host in allowed_hosts_raw.split(",")
                    if host.strip()
                )
                if allowed_hosts_raw
                else []
            ),
        }
        report["database_url"] = sanitize_database_url(args.database_url)
        report["postgres"] = postgres_identity(args.database_url)
    except Exception as exc:
        report["preflight_error"] = {
            "code": type(exc).__name__,
            "message": str(exc),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    env = os.environ.copy()
    env.update(
        {
            "FINTECH_APP_ENV": "test",
            "FINTECH_DATABASE_URL": args.database_url,
            "FINTECH_AUTH_PROVIDER": "mock",
            "FINTECH_EFATA_MODE": "mock",
            "FINTECH_EFATA_PLATFORM_BRIDGE_ENABLED": "false",
            "RUN_POSTGRES_INTEGRATION": "1",
        }
    )

    commands = [
        (
            "alembic_upgrade_head_1",
            [args.python, "-m", "alembic", "upgrade", "head"],
        ),
        (
            "postgres_concurrency_tests",
            [
                args.python,
                "-m",
                "pytest",
                "-q",
                "-rs",
                "tests/test_postgres_concurrency.py",
                "tests/test_postgresql_atomic_concurrency.py",
            ],
        ),
        (
            "full_backend_suite_postgres",
            [args.python, "-m", "pytest", "-q", "-rs"],
        ),
        (
            "alembic_downgrade_base",
            [args.python, "-m", "alembic", "downgrade", "base"],
        ),
    ]

    failed = False
    for name, command in commands:
        step = run_step(
            name=name,
            command=command,
            cwd=backend_root,
            env=env,
        )
        report["steps"].append(asdict(step))
        if step.status != "PASS":
            failed = True
            break

    if not failed:
        after_down = schema_inventory(args.database_url)
        report["schema_after_downgrade"] = after_down

        allowed_after_down = {"alembic_version"}
        unexpected = sorted(set(after_down["tables"]) - allowed_after_down)
        downgrade_schema_status = "PASS" if not unexpected else "FAIL"
        report["steps"].append(
            asdict(
                StepResult(
                    name="downgrade_schema_inventory",
                    status=downgrade_schema_status,
                    returncode=0 if not unexpected else 1,
                    duration_ms=0,
                    stdout_tail=json.dumps(
                        {
                            "tables": after_down["tables"],
                            "unexpected": unexpected,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        )
        failed = bool(unexpected)

    if not failed:
        for name, command in [
            (
                "alembic_upgrade_head_2",
                [args.python, "-m", "alembic", "upgrade", "head"],
            ),
            (
                "alembic_check",
                [args.python, "-m", "alembic", "check"],
            ),
        ]:
            step = run_step(
                name=name,
                command=command,
                cwd=backend_root,
                env=env,
            )
            report["steps"].append(asdict(step))
            if step.status != "PASS":
                failed = True
                break

    report["final_status"] = "FAIL" if failed else "PASS"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

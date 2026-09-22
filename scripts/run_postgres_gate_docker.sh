#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.postgres-gate.yml}"
REPORT="${POSTGRES_GATE_REPORT:-postgres_gate_report.json}"

cleanup() {
  docker compose -f "$COMPOSE_FILE" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker compose -f "$COMPOSE_FILE" up -d --wait

export FINTECH_DATABASE_URL="${FINTECH_DATABASE_URL:-postgresql+psycopg://fintech:fintech_ci_only@127.0.0.1:55432/fintech_ci}"
export RUN_POSTGRES_INTEGRATION=1
export FINTECH_POSTGRES_GATE_CONFIRM="I_UNDERSTAND_THIS_DATABASE_WILL_BE_DOWNGRADED"
export FINTECH_POSTGRES_GATE_ALLOWED_HOSTS="127.0.0.1,localhost"

uv run python scripts/postgres_gate.py \
  --database-url "$FINTECH_DATABASE_URL" \
  --report "$REPORT"

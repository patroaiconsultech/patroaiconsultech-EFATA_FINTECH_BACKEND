# EFATÀ Fintech — M2M R1 PostgreSQL CI Gate

## Scope

Evidence-only gate for the already-audited `M2M_R1_READ_ONLY`.

It does **not** implement new product behavior.

## Required branch

```text
feat/efata-fintech-m2m-r1-read-only
```

## Run

GitHub → Actions → `EFATA Fintech M2M R1 PostgreSQL Evidence` → Run workflow.

Select the controlled branch and enter:

```text
APPROVE_M2M_R1_POSTGRES_EVIDENCE
```

## What it proves

```text
Git provenance
exact functional source hashes
Python/uv toolchain
real PostgreSQL connectivity
Alembic upgrade to head
Alembic current/check
M2M feature flag default OFF
18 focused M2M tests on PostgreSQL
explicit M2M audit persistence on PostgreSQL
PostgreSQL concurrency tests
full backend regression on PostgreSQL
final migration state
```

## Intentionally NOT executed

```text
alembic downgrade base
real EFATÀ introspection
merge
deploy
M2M live enablement
LLM
```

`alembic downgrade base` is intentionally excluded because `MIG_0009_DOWNGRADE_001`
is a known separate blocker. The M2M gate must not disguise or reclassify that incident.

## Expected artifact

```text
efata-fintech-m2m-r1-postgres-evidence
```

Send that artifact to AO-01/Daniel unchanged.

If any step fails: stop at the first failing step. Do not patch automatically.

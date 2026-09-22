# Efatà — Backend R6

Backend FastAPI do marketplace bilateral de crédito estruturado. O serviço mantém a fundação R4 de tenant, membership, representação, documentos, qualificação e auditoria, e adiciona perfis de tomadores, provedores de funding, produtos, parceiros, demandas, documentos de demanda, matching explicável, eventos de match, comissão estimada e catálogo de agentes especializados.

## Local

```bash
uv sync --extra dev
cp .env.example .env
alembic upgrade head
python scripts/seed_demo.py
uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

O comando `python scripts/seed_demo.py` funciona a partir da raiz `backend/`. SQLite é o padrão local; PostgreSQL deve ser usado em staging/produção. O `Dockerfile` e `railway.json` já estão preparados para o serviço permanente no Railway e respeitam a porta `$PORT`.

## Testes

```bash
FINTECH_APP_ENV=test FINTECH_DATABASE_URL=sqlite:// FINTECH_AUTH_PROVIDER=mock uv run pytest -q
```

O teste de concorrência PostgreSQL fica condicionado à disponibilidade de um banco real. A autenticação por headers é exclusiva para local/teste.

## Superfície R6

| Endpoint | Uso |
|---|---|
| `/api/v1/marketplace/agents` | Catálogo interno de agentes, filas e próxima ação |
| `/api/v1/marketplace/borrower-profiles` | Perfil e contexto do tomador |
| `/api/v1/marketplace/funding-providers` | Cadastro de fundo, banco ou provedor |
| `/api/v1/marketplace/funding-products` | Produtos, tickets, prazos, tese e garantias |
| `/api/v1/marketplace/partners` | Canais de origem e atribuição |
| `/api/v1/marketplace/credit-requests` | Demandas de crédito e consentimento |
| `/api/v1/marketplace/credit-requests/{id}/documents` | Input e listagem documental com checksum mock |
| `/api/v1/marketplace/credit-requests/{id}/matching` | Matching determinístico para agentes internos |
| `/api/v1/marketplace/matches` | Fila e visibilidade de aderências |
| `/api/v1/marketplace/matches/{id}/status` | Encaminhamento e eventos de status |
| `/api/v1/marketplace/commission-events` | Comissão estimada, sem pagamento automático |

O catálogo `/agents` é restrito a `ANALYST`, `PLATFORM_ADMIN`, `INTERNAL_AGENT` e `CREDIT_ANALYST`. O release define seis agentes: Intake & Data, Credit Structuring, Funding Match, Partner & Origination, Deal Desk e Governance. Eles são funções operacionais governadas; o matching atual é determinístico e explicável, e toda ação relevante requer revisão humana.

## Demo IDs

| Papel | User | Tenant |
|---|---|---|
| Originador | `20000000-0000-0000-0000-000000000001` | `00000000-0000-0000-0000-000000000001` |
| Tomador/cliente | `20000000-0000-0000-0000-000000000002` | `00000000-0000-0000-0000-000000000002` |
| Agente interno | `20000000-0000-0000-0000-000000000003` | `00000000-0000-0000-0000-000000000003` |
| Funder | `20000000-0000-0000-0000-000000000004` | `00000000-0000-0000-0000-000000000004` |
| Parceiro | `20000000-0000-0000-0000-000000000005` | `00000000-0000-0000-0000-000000000005` |

A autenticação por headers e estes IDs são somente fixtures de demonstração. O modo compartilhado deve usar OIDC fail-closed, memberships locais provisionadas, storage privado e observabilidade.


## Superfície R7 — risco e governança

O `Credit Risk Agent` aplica a política versionada `credit-risk-demo-v1` sobre dados declarados e evidências disponíveis. Ele retorna score interno de triagem, faixa, regras, fontes, gaps e recomendação operacional; não aprova, recusa definitivamente nem define condições finais de crédito.

| Endpoint | Uso |
|---|---|
| `/api/v1/risk/simulate` | Simulação não persistida para preparação de captação |
| `/api/v1/risk/credit-requests/{id}/assessments` | Criar e listar avaliações persistidas, restritas ao time interno |
| `/api/v1/risk/governance-queue` | Fila de matches com avaliação mais recente e revisão humana |
| `/api/v1/risk/matches/{id}/governance-reviews` | Registrar `APPROVE_CONTACT`, `REQUEST_INFORMATION`, `BLOCK` ou `REJECT` com justificativa |

A liberação de contato exige avaliação sem hard gates ou pendências essenciais e uma revisão humana persistida. A migration `0003_risk_governance_r7.py` cria as tabelas de avaliações e revisões com rollback explícito. Consulte `CREDIT_RISK_AGENT_R7_SPEC.md` para a matriz completa e seus limites.

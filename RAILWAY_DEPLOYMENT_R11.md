# Efatà Backend R11 — Railway Deployment Runbook

## Escopo

Este runbook descreve a implantação do serviço FastAPI no Railway com PostgreSQL. O ambiente de produção deve usar OIDC real, secrets configurados no Railway e integração ERP somente leitura. A autenticação por headers `X-User-ID`, `X-Tenant-ID` e `X-Role` é exclusiva para teste/demo e não deve ser habilitada em produção.

## Serviços

1. Criar um serviço PostgreSQL privado no mesmo ambiente Railway do backend.
2. Criar o serviço backend a partir deste diretório e usar o `Dockerfile` presente.
3. Configurar a referência privada `FINTECH_DATABASE_URL=${{Postgres.DATABASE_URL}}` ou equivalente oferecida pelo Railway.
4. Configurar o domínio público apenas no serviço backend e restringir CORS ao domínio efetivo do frontend.

## Variáveis obrigatórias do backend

```text
FINTECH_APP_NAME=Efatà Fintech
FINTECH_APP_ENV=production
FINTECH_DATABASE_URL=${{Postgres.DATABASE_URL}}
FINTECH_AUTH_PROVIDER=oidc
FINTECH_OIDC_INTROSPECTION_ENDPOINT=https://<issuer>/oauth2/introspect
FINTECH_OIDC_INTROSPECTION_CLIENT_ID=<secret-in-Railway>
FINTECH_OIDC_INTROSPECTION_CLIENT_SECRET=<secret-in-Railway>
FINTECH_OIDC_ISSUER=https://<issuer>/
FINTECH_OIDC_AUDIENCE=<api-audience>
FINTECH_OIDC_USER_CLAIM=sub
FINTECH_OIDC_TENANT_CLAIM=tenant_id
FINTECH_OIDC_ROLES_CLAIM=roles
FINTECH_OIDC_HTTP_TIMEOUT_SECONDS=5
FINTECH_ERP_ENCRYPTION_KEY=<Fernet-key-in-Railway>
FINTECH_CORS_ALLOWED_ORIGINS=https://<frontend-domain>
FINTECH_EFATA_MODE=production
FINTECH_EFATA_CONTRACT_VERSION=r7-risk-governance-v1
FINTECH_PLATFORM_TENANT_ID=<production-tenant-uuid>
FINTECH_LOG_LEVEL=INFO
FINTECH_ERP_ALLOWED_HOSTS=<approved-sienge-and-mega-hosts>
FINTECH_ERP_HTTP_TIMEOUT_SECONDS=10
FINTECH_ERP_MAX_RECORDS_PER_RESOURCE=5000
```

Nunca incluir valores reais no repositório, ZIP, frontend, logs, tickets ou screenshots. `FINTECH_ERP_ENCRYPTION_KEY` deve ser uma chave Fernet gerada em ambiente seguro e armazenada como secret sealed.

## Ordem de implantação

1. Configurar PostgreSQL e verificar `DATABASE_URL` privado.
2. Configurar secrets OIDC, criptografia ERP, tenant de produção e allowlist ERP.
3. Configurar CORS com o domínio real do frontend.
4. Aplicar `preDeployCommand` do `railway.json`, que executa `alembic upgrade head`.
5. Verificar `/api/v1/health/live`.
6. Verificar `/api/v1/health/ready` com banco alcançável.
7. Executar smoke autenticado com token OIDC real.
8. Verificar isolamento de tenant, RBAC, criação de estudo, cálculo e snapshot.
9. Verificar que conexões ERP rejeitam HTTP, hosts fora da allowlist e escopos que não incluam `READ_ONLY`.
10. Somente depois permitir acesso ao domínio para usuários convidados.

## Healthcheck e porta

O serviço deve escutar em `0.0.0.0:${PORT}`. O healthcheck do Railway é `/api/v1/health/live`. O endpoint `/api/v1/health/ready` deve ser usado para validação operacional do banco, mas não deve ser exposto com informações sensíveis.

## Migrations

As migrations devem ser aplicadas pelo comando de pre-deploy do Railway. Nunca executar downgrade em produção como rotina. O ciclo `upgrade → downgrade → upgrade` foi validado localmente em SQLite para as migrations 0001–0009; o fluxo de produção deve ser testado previamente em uma cópia do PostgreSQL de homologação.

## Smoke mínimo

- OIDC: token válido, token expirado, issuer/audience inválidos e ausência de token.
- RBAC: operador interno, cliente, parceiro e tenant não autorizado.
- Viabilidade: criar estudo, cenário, calcular FCD, executar sensibilidade e congelar snapshot.
- ERP: criar conexão read-only, executar sync, visualizar resumo e aplicar patch somente com confirmação explícita.
- Segurança: headers, CORS, TLS, logs sem secrets e sem payloads sensíveis desnecessários.
- Dados: tenant isolation, migrations head, reconciliação e backup/restore.

## Rollback e incidentes

Em caso de falha de deploy, preservar logs com request/correlation ID, pausar o serviço de integração ERP se necessário, verificar migration e retornar ao último build estável. Não remover dados ou snapshots imutáveis para “corrigir” uma operação. Alterações de dados devem ocorrer por nova migration, evento de correção ou fluxo auditado.

## Checklist de go-live

- [ ] IdP real homologado.
- [ ] MFA e política de sessão revisados.
- [ ] PostgreSQL privado e backups configurados.
- [ ] Secrets configurados fora do repositório.
- [ ] Chave Fernet de produção criada e guardada em secret manager.
- [ ] CORS limitado ao frontend real.
- [ ] Allowlist ERP revisada.
- [ ] Migrations testadas em PostgreSQL.
- [ ] Smoke E2E aprovado.
- [ ] Isolamento de tenant testado.
- [ ] Logs e alertas configurados.
- [ ] Plano de incidentes e contatos definidos.
- [ ] Revisão jurídica/regulatória e LGPD concluída.

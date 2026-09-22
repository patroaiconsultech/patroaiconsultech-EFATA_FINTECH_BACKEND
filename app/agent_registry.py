from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    key: str
    name: str
    specialty: str
    description: str
    queue: str
    autonomy: str
    next_action: str
    human_review_required: bool = True


AGENT_REGISTRY: tuple[AgentDefinition, ...] = (
    AgentDefinition(
        key="intake_data",
        name="Intake & Data Agent",
        specialty="Entrada e completude",
        description="Organiza o cadastro, normaliza campos e identifica informações ou documentos ausentes.",
        queue="Novas demandas",
        autonomy="assistido",
        next_action="Validar dossiê mínimo",
    ),
    AgentDefinition(
        key="credit_structuring",
        name="Credit Structuring Agent",
        specialty="Estruturação de crédito",
        description="Transforma a necessidade do cliente em uma tese comparável de operação, garantias e pendências.",
        queue="Qualificação",
        autonomy="assistido",
        next_action="Revisar tese e garantias",
    ),
    AgentDefinition(
        key="funding_match",
        name="Funding Match Agent",
        specialty="Aderência de funding",
        description="Compara demandas qualificadas com mandatos e produtos ativos usando regras explicáveis.",
        queue="Matches sugeridos",
        autonomy="priorização",
        next_action="Revisar razões do match",
    ),
    AgentDefinition(
        key="partner_origination",
        name="Partner & Origination Agent",
        specialty="Originação e canais",
        description="Preserva origem, consentimento, atribuição e o relacionamento com parceiros indicantes.",
        queue="Canais e atribuição",
        autonomy="assistido",
        next_action="Confirmar atribuição e consentimento",
    ),
    AgentDefinition(
        key="deal_desk",
        name="Deal Desk Agent",
        specialty="Encaminhamento e próximos passos",
        description="Coordena interesse, diligência, contatos autorizados e tarefas entre as partes.",
        queue="Operações em andamento",
        autonomy="assistido",
        next_action="Preparar encaminhamento",
    ),
    AgentDefinition(
        key="governance_compliance",
        name="Governance Agent",
        specialty="Governança e visibilidade",
        description="Verifica consentimento, escopo de acesso, conflitos, disclosures e trilha de auditoria.",
        queue="Alertas e bloqueios",
        autonomy="bloqueio preventivo",
        next_action="Resolver pendência de governança",
    ),
    AgentDefinition(
        key="credit_risk",
        name="Credit Risk Agent",
        specialty="Triagem de risco de crédito",
        description="Aplica uma política versionada sobre dados e evidências declaradas, explicando alertas, gaps e recomendação para revisão humana.",
        queue="Risco e revisão",
        autonomy="recomendação assistida",
        next_action="Revisar avaliação e registrar decisão humana",
    ),
)


def get_agent_definition(key: str) -> AgentDefinition | None:
    return next((agent for agent in AGENT_REGISTRY if agent.key == key), None)

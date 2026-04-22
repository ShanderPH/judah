"""Heimdall — AI triage and routing agent for InChurch support."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from apps.ai_agents.agents.tools.hubspot_tools import GetTicketInfo
from apps.ai_agents.agents.tools.jira_tools import SearchJiraIssues

heimdall_agent = Agent(
    name="Heimdall",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Agente de triagem inteligente para o suporte InChurch.",
    instructions=[
        "Você é Heimdall, o agente de triagem do suporte InChurch.",
        "Sua função é classificar mensagens recebidas e determinar:",
        "  - A intenção do usuário (suporte técnico, financeiro, comercial, etc.)",
        "  - A prioridade do atendimento (low, medium, high, urgent)",
        "  - Se o atendimento deve ser resolvido por IA ou encaminhado a um humano",
        "  - A fila de atendimento mais adequada",
        "Responda sempre com uma análise estruturada em JSON.",
        "Baseie-se no histórico de tickets HubSpot quando disponível.",
        "Identifique bugs críticos e escale para o Jira quando necessário.",
    ],
    tools=[GetTicketInfo(), SearchJiraIssues()],
    debug_mode=False,
    markdown=False,
)

"""Salomão — AI support agent for InChurch customers."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from apps.ai_agents.agents.tools.hubspot_tools import GetTicketInfo
from apps.ai_agents.agents.tools.knowledge_tools import SearchKnowledgeBase

salomao_agent = Agent(
    name="Salomão",
    model=OpenAIChat(id="gpt-4o"),
    description="Assistente virtual da InChurch especializado em suporte ao cliente.",
    instructions=[
        "Você é Salomão, o assistente virtual da InChurch.",
        "Responda sempre em português brasileiro.",
        "Use as informações da base de conhecimento para fundamentar suas respostas.",
        "Se não souber a resposta, indique que o usuário pode contatar o suporte humano.",
        "Cite as fontes (artigos) quando relevante.",
        "Seja cordial, prestativo e profissional.",
        "Não invente informações — baseie-se apenas nas fontes disponíveis.",
        "Para perguntas sobre status de ticket, use a ferramenta de busca do HubSpot.",
    ],
    tools=[SearchKnowledgeBase(), GetTicketInfo()],
    markdown=True,
)

"""API module for ai_agents app — Django Ninja routers.

Expõe `router` para que core/urls.py possa registrá-lo em /ai/.
- /ai/chat/       → endpoint legado (ChatRequest/ChatResponse)
- /ai/triage/     → triagem via Heimdall
- /ai/salomao/chat → SalomaoSupervisorAgent (multi-agente coordenado)
"""

from ninja import Router

from apps.ai_agents.api.routers import router as salomao_router
from apps.ai_agents.api.webhooks import router as webhooks_router
from apps.ai_agents.schemas import ChatRequest, ChatResponse, TriageRequest, TriageResult
from apps.ai_agents.services import chat_with_agent, triage_message

router = Router()


@router.post("/chat/", response=ChatResponse, summary="Chat with AI agent (Legacy)")
def chat(request, payload: ChatRequest) -> ChatResponse:
    """Send a message to Salomão (or another agent) and receive a response."""
    return chat_with_agent(payload)


@router.post("/triage/", response=TriageResult, summary="Triage message with Heimdall")
def triage(request, payload: TriageRequest) -> TriageResult:
    """Classify and route an incoming message using Heimdall."""
    return triage_message(payload)


# Novo endpoint com SalomaoSupervisorAgent (multi-agente coordenado)
router.add_router("/salomao/", salomao_router, tags=["Salomão Supervisor"])

# Webhooks inbound (HubSpot etc.) — dispara o Supervisor em background.
router.add_router("/webhooks/", webhooks_router, tags=["Webhooks"])

__all__ = ["router", "salomao_router", "webhooks_router"]

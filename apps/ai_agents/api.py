"""Django Ninja API endpoints for AI agents."""

from ninja import Router

from apps.ai_agents.schemas import ChatRequest, ChatResponse, TriageRequest, TriageResult
from apps.ai_agents.services import chat_with_agent, triage_message

router = Router()


@router.post("/chat/", response=ChatResponse, summary="Chat with AI agent")
def chat(request, payload: ChatRequest) -> ChatResponse:
    """Send a message to Salomão (or another agent) and receive a response."""
    return chat_with_agent(payload)


@router.post("/triage/", response=TriageResult, summary="Triage message with Heimdall")
def triage(request, payload: TriageRequest) -> TriageResult:
    """Classify and route an incoming message using Heimdall."""
    return triage_message(payload)

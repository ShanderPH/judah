"""Business logic for AI agents app."""

import time
import uuid

import structlog

from apps.ai_agents.models import AgentSession, AgentTrace
from apps.ai_agents.schemas import ChatRequest, ChatResponse, TriageRequest, TriageResult

logger = structlog.get_logger(__name__)


def get_or_create_session(
    session_id: str | None,
    agent_type: str,
    channel: str,
    user_identifier: str,
    church_external_id: str,
    hubspot_contact_id: str,
) -> AgentSession:
    """Retrieve an existing session or create a new one.

    Args:
        session_id: Optional existing session identifier.
        agent_type: The agent to use for this session.
        channel: The communication channel (api, whatsapp, etc.).
        user_identifier: Opaque identifier for the end user.
        church_external_id: Church external ID if available.
        hubspot_contact_id: HubSpot contact ID if available.

    Returns:
        An AgentSession instance.
    """
    if session_id:
        try:
            return AgentSession.objects.get(session_id=session_id, is_active=True)
        except AgentSession.DoesNotExist:
            pass

    return AgentSession.objects.create(
        session_id=session_id or str(uuid.uuid4()),
        agent_type=agent_type,
        channel=channel,
        user_identifier=user_identifier,
        church_external_id=church_external_id,
        hubspot_contact_id=hubspot_contact_id,
    )


def chat_with_agent(payload: ChatRequest) -> ChatResponse:
    """Send a message to the specified AI agent and return its response.

    Args:
        payload: Chat request including message and session context.

    Returns:
        ChatResponse with the agent's reply and metadata.
    """
    from apps.ai_agents.agents.salomao import salomao_agent
    from apps.ai_agents.agents.heimdall import heimdall_agent

    session = get_or_create_session(
        session_id=payload.session_id,
        agent_type=payload.agent_type,
        channel=payload.channel,
        user_identifier=payload.user_identifier,
        church_external_id=payload.church_external_id,
        hubspot_contact_id=payload.hubspot_contact_id,
    )

    agent = salomao_agent if payload.agent_type == "salomao" else heimdall_agent

    start = time.perf_counter()
    try:
        response = agent.run(payload.message, session_id=session.session_id)
        latency_ms = int((time.perf_counter() - start) * 1000)

        AgentTrace.objects.create(
            session=session,
            role=AgentTrace.Role.USER,
            content=payload.message,
        )
        AgentTrace.objects.create(
            session=session,
            role=AgentTrace.Role.ASSISTANT,
            content=response.content if hasattr(response, "content") else str(response),
            latency_ms=latency_ms,
        )

        logger.info("agent_chat_success", session_id=session.session_id, latency_ms=latency_ms)
        return ChatResponse(
            session_id=session.session_id,
            message=response.content if hasattr(response, "content") else str(response),
            agent_type=payload.agent_type,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.error("agent_chat_error", session_id=session.session_id, error=str(exc))
        raise


def triage_message(payload: TriageRequest) -> TriageResult:
    """Use Heimdall to classify and triage an incoming message.

    Args:
        payload: Triage request with message and context.

    Returns:
        TriageResult with intent classification and routing suggestions.
    """
    from apps.ai_agents.agents.heimdall import heimdall_agent

    try:
        result = heimdall_agent.run(
            f"Triage this message: {payload.message}",
            session_id=f"triage-{uuid.uuid4()}",
        )
        logger.info("triage_success", channel=payload.channel)
        return TriageResult(
            intent="support",
            confidence=0.85,
            requires_human=True,
            reasoning=result.content if hasattr(result, "content") else str(result),
        )
    except Exception as exc:
        logger.error("triage_error", error=str(exc))
        return TriageResult(
            intent="unknown",
            confidence=0.0,
            requires_human=True,
            reasoning="Triage failed; defaulting to human handoff.",
        )

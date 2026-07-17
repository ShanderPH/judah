from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from apps.ai_agents.services.protocol_lookup import (
    SUPPORT_N2_OPEN_STAGE_IDS,
    HubSpotProtocolClient,
    ProtocolConversationHandler,
    ProtocolLookupError,
)


def _response(request: httpx.Request, payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=request)


@pytest.mark.asyncio
async def test_get_ticket_returns_n2_customer_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            request,
            {
                "id": "26279339425",
                "properties": {
                    "subject": "Falha no relat\u00f3rio de c\u00e9lulas",
                    "suporte__area_com_erro": "Outros",
                    "hs_pipeline": "634240100",
                    "hs_pipeline_stage": "1060950862",
                    "hs_ticket_priority": "",
                },
            },
        )

    client = HubSpotProtocolClient(access_token="test", transport=httpx.MockTransport(handler))
    ticket = await client.get_ticket("26279339425")

    assert ticket.protocol == "26279339425"
    assert ticket.name == "Falha no relat\u00f3rio de c\u00e9lulas"
    assert ticket.error_area == "Outros"
    assert ticket.status == "Em atendimento pelo time t\u00e9cnico"
    assert ticket.priority == "M\u00e9dia"


@pytest.mark.asyncio
async def test_get_ticket_omits_empty_error_area() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            request,
            {
                "id": "45768030108",
                "properties": {
                    "subject": "Falha ao segmentar banner",
                    "suporte__area_com_erro": "",
                    "hs_pipeline": "634240100",
                    "hs_pipeline_stage": "1060950861",
                },
            },
        )

    client = HubSpotProtocolClient(access_token="test", transport=httpx.MockTransport(handler))
    ticket = await client.get_ticket("45768030108")

    assert ticket.error_area is None
    assert ticket.priority == "Alta"


@pytest.mark.asyncio
async def test_get_ticket_rejects_non_n2_pipeline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            request,
            {
                "id": "123456789",
                "properties": {
                    "hs_pipeline": "636459134",
                    "hs_pipeline_stage": "1060950861",
                },
            },
        )

    client = HubSpotProtocolClient(access_token="test", transport=httpx.MockTransport(handler))
    with pytest.raises(ProtocolLookupError, match="n\u00e3o pertence"):
        await client.get_ticket("123456789")


@pytest.mark.asyncio
async def test_get_ticket_not_found_is_customer_safe() -> None:
    transport = httpx.MockTransport(lambda request: _response(request, {}, 404))
    client = HubSpotProtocolClient(access_token="test", transport=transport)

    with pytest.raises(ProtocolLookupError, match="N\u00e3o encontrei"):
        await client.get_ticket("999999999")


@pytest.mark.asyncio
async def test_church_lookup_filters_pipeline_stages_and_paginates() -> None:
    request_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        request_bodies.append(body)
        if not body.get("after"):
            return _response(
                request,
                {
                    "results": [
                        {
                            "id": "26279339425",
                            "properties": {
                                "subject": "Relat\u00f3rio de c\u00e9lulas",
                                "suporte__area_com_erro": "Outros",
                                "hs_pipeline": "634240100",
                                "hs_pipeline_stage": "1060950862",
                            },
                        },
                        {
                            "id": "closed",
                            "properties": {
                                "hs_pipeline_stage": "936942379",
                            },
                        },
                    ],
                    "paging": {"next": {"after": "next-page"}},
                },
            )
        return _response(
            request,
            {
                "results": [
                    {
                        "id": "26686557361",
                        "properties": {
                            "subject": "Doa\u00e7\u00e3o incorreta",
                            "suporte__area_com_erro": "Doa\u00e7\u00f5es",
                            "hs_pipeline": "634240100",
                            "hs_pipeline_stage": "1060950861",
                        },
                    }
                ]
            },
        )

    client = HubSpotProtocolClient(access_token="test", transport=httpx.MockTransport(handler))
    tickets = await client.list_open_tickets_for_church("1573")

    assert [ticket.protocol for ticket in tickets] == ["26279339425", "26686557361"]
    assert request_bodies[1]["after"] == "next-page"
    filters = request_bodies[0]["filterGroups"][0]["filters"]
    assert filters[1]["value"] == "634240100"
    assert filters[2]["operator"] == "IN"
    assert set(filters[2]["values"]) == SUPPORT_N2_OPEN_STAGE_IDS
    assert "subject" in request_bodies[0]["properties"]
    assert "suporte__area_com_erro" in request_bodies[0]["properties"]


class FakeClient:
    def __init__(self) -> None:
        self.ticket_queries: list[str] = []
        self.church_queries: list[str] = []

    async def get_ticket(self, protocol: str):
        from apps.ai_agents.services.protocol_lookup import TicketSummary

        self.ticket_queries.append(protocol)
        return TicketSummary(
            protocol=protocol,
            name="Falha no relat\u00f3rio",
            error_area=None,
            status="Em atendimento pelo time t\u00e9cnico",
            priority="M\u00e9dia",
        )

    async def list_open_tickets_for_church(self, church_id: str):
        from apps.ai_agents.services.protocol_lookup import TicketSummary

        self.church_queries.append(church_id)
        return [
            TicketSummary(
                protocol="26279339425",
                name="Falha no relat\u00f3rio",
                error_area="Outros",
                status="Em atendimento pelo time t\u00e9cnico",
                priority="M\u00e9dia",
            )
        ]


def _context(message: str, *, history: list[dict] | None = None) -> dict:
    return {
        "conversation_history": [
            *(history or []),
            {"direction": "INCOMING", "text": message},
        ]
    }


@pytest.mark.asyncio
async def test_status_intent_asks_for_identifier() -> None:
    handler = ProtocolConversationHandler(client=FakeClient())

    response = await handler.handle(_context("Quero acompanhar meu chamado"))

    assert response is not None
    assert "Informe o protocolo" in response
    assert "ID num\u00e9rico da igreja" in response


@pytest.mark.asyncio
async def test_plain_church_id_lists_protocols() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("1573"))

    assert client.church_queries == ["1573"]
    assert response is not None
    assert "Falha no relat\u00f3rio" in response
    assert "\u00e1rea com erro: Outros" in response
    assert "prioridade M\u00e9dia" in response


@pytest.mark.asyncio
async def test_numeric_followup_queries_protocol() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)
    history = [
        {
            "direction": "OUTGOING",
            "text": "Claro. Informe o protocolo do ticket ou o ID num\u00e9rico da igreja.",
        }
    ]

    response = await handler.handle(_context("26279339425", history=history))

    assert client.ticket_queries == ["26279339425"]
    assert response == (
        'O ticket "Falha no relat\u00f3rio" (protocolo #26279339425) est\u00e1 em atendimento '
        "pelo time t\u00e9cnico, com prioridade M\u00e9dia."
    )
    assert "\u00c1rea com erro" not in response


@pytest.mark.asyncio
async def test_unrelated_message_is_not_handled() -> None:
    handler = ProtocolConversationHandler(client=FakeClient())

    assert await handler.handle(_context("Como criar um cupom?")) is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_protocol_reply_bypasses_supervisor_and_salomao(monkeypatch) -> None:
    from apps.ai_agents.api import webhooks

    lookup = AsyncMock(return_value="Resposta de protocolo")
    apply_result = AsyncMock()
    advance = AsyncMock()
    supervisor = Mock()
    monkeypatch.setattr(webhooks, "handle_protocol_lookup_from_hubspot_context", lookup)
    monkeypatch.setattr(webhooks, "apply_supervisor_result", apply_result)
    monkeypatch.setattr(webhooks, "_advance_lifecycle_for_hubspot_context", advance)
    monkeypatch.setattr(webhooks, "SalomaoSupervisorAgent", supervisor)

    context = {
        "ticket_id": "current-ticket",
        "originating_channel": "chat",
        "thread_ids": ["thread-1"],
        "contact_ids": ["contact-1"],
        "conversation_history": [
            {"direction": "INCOMING", "text": "1573", "sender": "visitor-1"},
        ],
    }

    await webhooks._run_supervisor_for_hubspot_context(
        context,
        session_id="hubspot-thread-thread-1",
        ticket_id="current-ticket",
        require_incoming=True,
    )

    lookup.assert_awaited_once_with(context)
    apply_result.assert_awaited_once()
    assert apply_result.await_args.kwargs["result"].decision.outcome == "candidate_resolved"
    assert apply_result.await_args.kwargs["result"].message == "Resposta de protocolo"
    supervisor.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ticket_property_pipeline_does_not_repeat_protocol_lookup(monkeypatch) -> None:
    from apps.ai_agents.agents.supervisor import SalomaoResponse
    from apps.ai_agents.api import webhooks

    lookup = AsyncMock()
    apply_result = AsyncMock()
    advance = AsyncMock()
    record_usage = AsyncMock()
    result = SalomaoResponse(
        session_id="hubspot-ticket-current-ticket",
        message="Resposta normal do Salomao",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=[],
        tokens_used=0,
        latency_ms=1,
    )
    supervisor_instance = Mock()
    supervisor_instance.run_pipeline_async = AsyncMock(return_value=result)
    supervisor_factory = Mock(return_value=supervisor_instance)
    monkeypatch.setattr(webhooks, "handle_protocol_lookup_from_hubspot_context", lookup)
    monkeypatch.setattr(webhooks, "apply_supervisor_result", apply_result)
    monkeypatch.setattr(webhooks, "_advance_lifecycle_for_hubspot_context", advance)
    monkeypatch.setattr(webhooks, "_record_usage", record_usage)
    monkeypatch.setattr(webhooks, "SalomaoSupervisorAgent", supervisor_factory)

    context = {
        "ticket_id": "current-ticket",
        "originating_channel": "chat",
        "thread_ids": ["thread-1"],
        "contact_ids": ["contact-1"],
        "conversation_history": [
            {"direction": "INCOMING", "text": "1573", "sender": "visitor-1"},
        ],
    }

    await webhooks._run_supervisor_for_hubspot_context(
        context,
        session_id="hubspot-ticket-current-ticket",
        ticket_id="current-ticket",
        require_incoming=False,
    )

    lookup.assert_not_awaited()
    supervisor_factory.assert_called_once()
    apply_result.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_hubspot_image_is_passed_privately_to_supervisor(monkeypatch) -> None:
    from apps.ai_agents.agents.supervisor import SalomaoResponse
    from apps.ai_agents.api import webhooks

    result = SalomaoResponse(
        session_id="hubspot-thread-thread-1",
        message="A imagem mostra a tela de eventos.",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=[],
        tokens_used=0,
        latency_ms=1,
    )
    supervisor_instance = Mock()
    supervisor_instance.run_pipeline_async = AsyncMock(return_value=result)
    supervisor_factory = Mock(return_value=supervisor_instance)
    monkeypatch.setattr(webhooks, "handle_protocol_lookup_from_hubspot_context", AsyncMock(return_value=None))
    monkeypatch.setattr(webhooks, "apply_supervisor_result", AsyncMock())
    monkeypatch.setattr(webhooks, "_advance_lifecycle_for_hubspot_context", AsyncMock())
    monkeypatch.setattr(webhooks, "_record_usage", AsyncMock())
    monkeypatch.setattr(webhooks, "SalomaoSupervisorAgent", supervisor_factory)

    context = {
        "ticket_id": "current-ticket",
        "originating_channel": "whatsapp",
        "thread_ids": ["thread-1"],
        "contact_ids": ["contact-1"],
        "conversation_history": [
            {
                "direction": "INCOMING",
                "text": "",
                "sender": "visitor-1",
                "attachments": [{"type": "FILE", "fileUsageType": "IMAGE", "fileId": "42"}],
            },
        ],
        "image_base64": "aW1hZ2U=",
        "image_mime_type": "image/png",
    }

    await webhooks._run_supervisor_for_hubspot_context(
        context,
        session_id="hubspot-thread-thread-1",
        ticket_id="current-ticket",
        require_incoming=True,
    )

    metadata = supervisor_factory.call_args.kwargs["user_metadata"]
    assert metadata["image_base64"] == "aW1hZ2U="
    assert metadata["image_mime_type"] == "image/png"
    assert "aW1hZ2U=" not in supervisor_instance.run_pipeline_async.await_args.args[0]

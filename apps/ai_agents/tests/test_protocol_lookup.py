from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from django.utils import timezone

from apps.ai_agents.services.protocol_lookup import (
    SUPPORT_N2_OPEN_STAGE_IDS,
    DjangoProtocolRepository,
    HubSpotProtocolClient,
    ProtocolConversationHandler,
    ProtocolLookupError,
)
from apps.support.models import Ticket
from apps.webhooks.models import WebhookEvent


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
@pytest.mark.parametrize(
    "stage_id",
    ["1028692851", "1208927005", "1368995876", "1368995712", "1368986534"],
)
async def test_get_ticket_hides_non_tracking_stages(stage_id: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            request,
            {
                "id": "46667856488",
                "properties": {
                    "subject": "Caso encerrado",
                    "hs_pipeline": "634240100",
                    "hs_pipeline_stage": stage_id,
                },
            },
        )

    client = HubSpotProtocolClient(access_token="test", transport=httpx.MockTransport(handler))

    with pytest.raises(ProtocolLookupError, match="casos em acompanhamento"):
        await client.get_ticket("46667856488")


@pytest.mark.asyncio
async def test_church_lookup_filters_closed_n2_stages_and_paginates() -> None:
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
                            "id": "26279339999",
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
    assert "936942379" not in filters[2]["values"]
    assert "1028692851" not in filters[2]["values"]
    assert "1208927005" not in filters[2]["values"]
    assert "1368995876" not in filters[2]["values"]
    assert "1368995712" not in filters[2]["values"]
    assert "1368986534" not in filters[2]["values"]
    assert "subject" in request_bodies[0]["properties"]
    assert "suporte__area_com_erro" in request_bodies[0]["properties"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_staging_hubspot_falls_back_to_supabase_ticket_mirror() -> None:
    await Ticket.objects.acreate(
        ticket_id="46667856488",
        ticket_church="S3428-T30540// Igreja Mananciais",
        category="Bug Report",
        priority="P2-M\u00e9dio",
        status="RESOLVED",
        affected_module="M\u00f3dulo de Pessoas",
        affected_functionality="Pessoas | Membros",
        created_at=timezone.now(),
    )
    await WebhookEvent.objects.acreate(
        event_type="ticket.propertyChange",
        event_id="stage-open",
        object_id="46667856488",
        property_name="hs_pipeline_stage",
        property_value="1110524173",
        payload={},
    )
    transport = httpx.MockTransport(lambda request: _response(request, {}, 404))
    client = HubSpotProtocolClient(
        access_token="sandbox-token",
        transport=transport,
        local_repository=DjangoProtocolRepository(),
    )

    ticket = await client.get_ticket("46667856488")

    assert ticket.name == "M\u00f3dulo de Pessoas \u2014 Pessoas | Membros"
    assert ticket.status == "Em triagem pelo time t\u00e9cnico"
    assert ticket.priority == "M\u00e9dia"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_staging_hubspot_falls_back_to_open_church_cases_only() -> None:
    for protocol, stage_id in (
        ("39580297219", "1110524173"),
        ("46793834757", "1028692851"),
    ):
        await Ticket.objects.acreate(
            ticket_id=protocol,
            ticket_church="S4491-T35120// Igreja Esperan\u00e7a",
            category="Bug Report",
            priority="P2-M\u00e9dio",
            status="RESOLVED",
            affected_module="M\u00f3dulo de Pessoas",
            affected_functionality="Pessoas | Membros",
            created_at=timezone.now(),
        )
        await WebhookEvent.objects.acreate(
            event_type="ticket.propertyChange",
            event_id=f"stage-{protocol}",
            object_id=protocol,
            property_name="hs_pipeline_stage",
            property_value=stage_id,
            payload={},
        )
    transport = httpx.MockTransport(lambda request: _response(request, {"results": []}))
    client = HubSpotProtocolClient(
        access_token="sandbox-token",
        transport=transport,
        local_repository=DjangoProtocolRepository(),
    )

    tickets = await client.list_open_tickets_for_church("35120")

    assert [ticket.protocol for ticket in tickets] == ["39580297219"]


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
    assert "n\u00famero do protocolo" in response
    assert "ID da igreja local" in response


@pytest.mark.asyncio
async def test_status_intent_asks_before_using_contextual_church_id() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)
    context = _context("Quero saber como est\u00e1 meu protocolo")
    context["church_id"] = "T35120"

    response = await handler.handle(context)

    assert client.ticket_queries == []
    assert client.church_queries == []
    assert response == handler.REQUEST_MESSAGE


@pytest.mark.asyncio
async def test_reported_case_question_asks_for_protocol_or_church_id() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("quero saber sobre o caso que reportei"))

    assert client.ticket_queries == []
    assert client.church_queries == []
    assert response == handler.REQUEST_MESSAGE
    assert "um caso espec\u00edfico" in response
    assert "todos os casos em acompanhamento" in response


@pytest.mark.asyncio
async def test_status_intent_never_treats_current_chat_ticket_as_requested_protocol() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)
    context = _context("Quero saber como est\u00e1 meu protocolo")
    context["ticket_id"] = "47029795230"

    response = await handler.handle(context)

    assert client.ticket_queries == []
    assert client.church_queries == []
    assert response == handler.REQUEST_MESSAGE


@pytest.mark.asyncio
async def test_explicit_church_id_phrase_lists_protocols() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("O ID da igreja local \u00e9 35120"))

    assert client.church_queries == ["35120"]
    assert response is not None
    assert "igreja 35120" in response


@pytest.mark.asyncio
async def test_plain_church_id_lists_protocols() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("1573"))

    assert client.church_queries == ["1573"]
    assert response is not None
    assert "**T\u00edtulo:** Falha no relat\u00f3rio" in response
    assert "**Status:** Em atendimento pelo time t\u00e9cnico" in response
    assert "**Prioridade:** M\u00e9dia" in response
    assert "**\u00c1rea com erro:** Outros" in response


@pytest.mark.asyncio
async def test_typical_five_digit_local_church_id_lists_church_protocols() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("35120"))

    assert client.church_queries == ["35120"]
    assert client.ticket_queries == []
    assert response is not None


@pytest.mark.asyncio
async def test_explicit_protocol_intent_wins_even_for_a_five_digit_number() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("Quero o status do protocolo 35120"))

    assert client.ticket_queries == ["35120"]
    assert client.church_queries == []
    assert response is not None


@pytest.mark.asyncio
async def test_explicit_church_intent_accepts_an_unusually_long_local_id() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("ID da igreja local: 12345678"))

    assert client.church_queries == ["12345678"]
    assert client.ticket_queries == []
    assert response is not None


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
        "Encontrei o ticket solicitado:\n\n"
        "- **Protocolo:** #26279339425\n"
        "- **T\u00edtulo:** Falha no relat\u00f3rio\n"
        "- **Status:** Em atendimento pelo time t\u00e9cnico\n"
        "- **Prioridade:** M\u00e9dia"
    )
    assert "\u00c1rea com erro" not in response


@pytest.mark.asyncio
async def test_five_digit_followup_after_identifier_question_queries_church() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)
    history = [{"direction": "OUTGOING", "text": handler.REQUEST_MESSAGE}]

    response = await handler.handle(_context("35120", history=history))

    assert client.ticket_queries == []
    assert client.church_queries == ["35120"]
    assert response is not None
    assert "igreja 35120" in response


@pytest.mark.asyncio
async def test_ticket_response_keeps_required_fields_when_priority_is_missing() -> None:
    from apps.ai_agents.services.protocol_lookup import TicketSummary

    client = FakeClient()
    client.get_ticket = AsyncMock(
        return_value=TicketSummary(
            protocol="46667856488",
            name="Falha ao confirmar pedido de ora\u00e7\u00e3o",
            error_area=None,
            status="Sendo analisado pelo time t\u00e9cnico",
            priority=None,
        )
    )
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(_context("Status do protocolo 46667856488"))

    assert response is not None
    assert "**T\u00edtulo:** Falha ao confirmar pedido de ora\u00e7\u00e3o" in response
    assert "**Status:** Sendo analisado pelo time t\u00e9cnico" in response
    assert "**Prioridade:** N\u00e3o informada" in response


@pytest.mark.asyncio
async def test_numeric_protocol_after_status_question_survives_unhelpful_outgoing_reply() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)
    history = [
        {"direction": "INCOMING", "text": "Quero saber como est\u00e1 meu protocolo"},
        {"direction": "OUTGOING", "text": "N\u00e3o tenho uma atualiza\u00e7\u00e3o dispon\u00edvel."},
    ]

    response = await handler.handle(_context("46667856488", history=history))

    assert client.ticket_queries == ["46667856488"]
    assert response is not None
    assert "**Protocolo:** #46667856488" in response


@pytest.mark.asyncio
async def test_explicit_protocol_takes_precedence_over_church_id() -> None:
    client = FakeClient()
    handler = ProtocolConversationHandler(client=client)

    response = await handler.handle(
        _context("Quero o status do protocolo 46667856488. O ID da igreja local \u00e9 35120.")
    )

    assert client.ticket_queries == ["46667856488"]
    assert client.church_queries == []
    assert response is not None


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
async def test_ticket_property_pipeline_uses_protocol_lookup_for_incoming_history(monkeypatch) -> None:
    from apps.ai_agents.agents.supervisor import SalomaoResponse
    from apps.ai_agents.api import webhooks

    lookup = AsyncMock(return_value="Resposta de protocolo")
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

    lookup.assert_awaited_once_with(context)
    supervisor_factory.assert_not_called()
    apply_result.assert_awaited_once()
    assert apply_result.await_args.kwargs["result"].message == "Resposta de protocolo"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_duplicate_ticket_property_turn_stops_before_lookup_or_model(monkeypatch) -> None:
    from apps.ai_agents.api import webhooks
    from apps.ai_agents.models import ConversationInstance, ToolCallAuditLog

    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:thread-duplicate",
        hubspot_thread_id="thread-duplicate",
        hubspot_ticket_id="ticket-duplicate",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        last_message_id="message-duplicate",
        ai_session_id="hubspot-thread-thread-duplicate",
    )
    await ToolCallAuditLog.objects.acreate(
        instance=instance,
        tool_name="send_thread_reply",
        idempotency_key=f"reply:{instance.pk}:message-duplicate",
        status=ToolCallAuditLog.Status.SUCCEEDED,
        output={"sent": True, "message_id": "out-duplicate"},
    )
    lookup = AsyncMock()
    supervisor = Mock()
    monkeypatch.setattr(webhooks, "handle_protocol_lookup_from_hubspot_context", lookup)
    monkeypatch.setattr(webhooks, "SalomaoSupervisorAgent", supervisor)

    await webhooks._run_supervisor_for_hubspot_context(
        {
            "ticket_id": "ticket-duplicate",
            "originating_channel": "chat",
            "thread_ids": ["thread-duplicate"],
            "conversation_history": [
                {
                    "id": "message-duplicate",
                    "direction": "INCOMING",
                    "text": "quero saber sobre o caso que reportei",
                }
            ],
        },
        session_id="hubspot-thread-thread-duplicate",
        ticket_id="ticket-duplicate",
        require_incoming=False,
    )

    lookup.assert_not_awaited()
    supervisor.assert_not_called()


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
        "image_name": "captura.png",
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
    assert metadata["image_name"] == "captura.png"
    assert "aW1hZ2U=" not in supervisor_instance.run_pipeline_async.await_args.args[0]

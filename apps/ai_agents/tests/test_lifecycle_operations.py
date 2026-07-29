"""Tests for lifecycle guardrails, handoff packages, and watchdog recovery."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from django.utils import timezone

from apps.ai_agents.contracts import ConversationContext, ConversationMessage, TriageDecision
from apps.ai_agents.models import ConversationEvent, ConversationInstance
from apps.ai_agents.services.execution import schedule_stale_turn_followup
from apps.ai_agents.services.handoff import (
    assess_customer_tone,
    build_handoff_package,
    format_handoff_observation,
)
from apps.ai_agents.services.tool_permissions import is_tool_allowed
from apps.ai_agents.services.watchdog import (
    reconcile_waiting_customer_messages,
    run_lifecycle_watchdog,
    waiting_customer_instances,
)


def test_tool_permissions_are_state_scoped() -> None:
    assert is_tool_allowed(ConversationInstance.State.AI_SERVICE_RUNNING, "send_thread_reply") is True
    assert is_tool_allowed(ConversationInstance.State.HUMAN_HANDOFF_REQUESTED, "assign_ticket_to_human_queue") is True
    assert is_tool_allowed(ConversationInstance.State.CLOSED, "send_thread_reply") is False
    assert is_tool_allowed(ConversationInstance.State.TRIAGE_RUNNING, "create_contact") is False


@pytest.mark.django_db
def test_build_handoff_package_includes_operational_context() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:thread-1",
        hubspot_thread_id="thread-1",
        hubspot_ticket_id="ticket-1",
        hubspot_contact_id="contact-1",
        channel="chat",
        state=ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        last_message_id="m1",
    )
    context = ConversationContext(
        channel="hubspot",
        session_id="hubspot-thread-thread-1",
        church_id="653",
        recent_messages=[
            ConversationMessage(direction="INCOMING", text="Preciso falar com humano", message_id="m1"),
        ],
    )
    triage = TriageDecision(
        rota="ESCALAR_IMEDIATAMENTE",
        prioridade="ALTA",
        sentimento="negativo",
        tags=["humano"],
    )

    package = build_handoff_package(
        instance=instance,
        reason="User requested a human.",
        conversation_context=context,
        triage_decision=triage,
        ai_summary="Cliente pediu atendimento humano.",
        feature_subscription_lookup={
            "church_id": "653",
            "module_lookup_status": "success",
            "module_lookup_message": "",
            "obtained_modules": [
                {
                    "alias": "kids",
                    "name": "1001 - 2500 pessoas na igreja",
                    "price": "329.90",
                    "plan_limit": "2500",
                },
                {
                    "alias": "smart_store",
                    "name": "Loja",
                    "price": "199.90",
                    "plan_limit": None,
                },
            ],
        },
        church_plan_lookup={
            "church_plan_lookup_status": "success",
            "church_plan_lookup_message": "",
            "church_plan": {
                "plan": "pro",
                "is_active": True,
                "is_blocked": False,
            },
        },
    )

    assert package["hubspot_thread_id"] == "thread-1"
    assert package["source_message_id"] == "m1"
    assert package["reason"] == "User requested a human."
    assert package["priority"] == "ALTA"
    assert package["tags"] == ["humano"]
    assert package["recent_messages"][0]["text"] == "Preciso falar com humano"
    assert package["church_id"] == "653"
    assert package["obtained_modules"][0]["alias"] == "kids"
    assert package["obtained_modules"][0]["name"] == "1001 - 2500 pessoas na igreja"
    assert package["obtained_modules"][0]["price"] == "329.90"
    assert package["church_plan"] == {
        "plan": "pro",
        "is_active": True,
        "is_blocked": False,
    }
    assert package["customer_tone"] == "Frustrado"
    assert "pediu continuidade com um atendente humano" in package["conversation_summary"]
    assert "histórico" in package["recommended_next_step"]

    observation = format_handoff_observation(package)
    assert "## Resumo automático do Salomão para o N1" in observation
    assert "**Tom do cliente:** Frustrado" in observation
    assert "**Resumo da conversa:**" in observation
    assert "**Plano da igreja:** `pro` — **is_active:** Sim; **is_blocked:** Não" in observation
    assert "**Módulos obtidos:**" in observation
    assert "`kids` — name: 1001 - 2500 pessoas na igreja, price: 329.90, limite 2500" in observation
    assert "`smart_store` — name: Loja, price: 199.90" in observation
    assert "**Próximo passo recomendado:**" in observation
    assert "**Prioridade da triagem:** Alta" in observation


def test_customer_tone_uses_observable_language_and_remains_conservative() -> None:
    irritated_context = ConversationContext(
        channel="hubspot",
        session_id="tone-irritated",
        recent_messages=[
            ConversationMessage(
                direction="INCOMING",
                text="Isso é um absurdo, ninguém responde e essa porra não funciona.",
            ),
        ],
    )
    neutral_context = ConversationContext(
        channel="hubspot",
        session_id="tone-neutral",
        recent_messages=[
            ConversationMessage(direction="INCOMING", text="Preciso de ajuda para cadastrar um membro."),
        ],
    )

    assert assess_customer_tone(irritated_context, None)[0] == "Irritado/agressivo"
    assert assess_customer_tone(neutral_context, None)[0] == "Calmo/neutro"


@pytest.mark.django_db
def test_handoff_observation_synthesizes_long_event_conversation_for_n1() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:event-handoff",
        hubspot_thread_id="event-handoff",
        hubspot_ticket_id="ticket-event-handoff",
        channel="chat",
        state=ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        last_message_id="event-message-6",
    )
    context = ConversationContext(
        channel="hubspot",
        session_id="event-handoff",
        recent_messages=[
            ConversationMessage(
                direction="INCOMING",
                text="Quero criar um ingresso pago para o evento de Natal.",
            ),
            ConversationMessage(
                direction="INCOMING",
                text="Quero limitar a 200 ingressos, aceitar PIX e cartão e definir uma data final.",
            ),
            ConversationMessage(
                direction="INCOMING",
                text="Preciso pedir dados do participante e tamanho de camiseta na inscrição.",
            ),
            ConversationMessage(
                direction="OUTGOING",
                text=(
                    "### Como configurar os campos da inscrição\n"
                    "1. Acesse o **Painel v2** e vá em: **Programação > Eventos**.\n"
                    "2. Abra o evento e configure todos os passos detalhados."
                ),
            ),
            ConversationMessage(
                direction="INCOMING",
                text=(
                    "Quero que a pessoa receba uma confirmação e o ingresso depois do pagamento. "
                    "Também preciso saber como fazer o estorno e registrar o cancelamento."
                ),
            ),
            ConversationMessage(
                direction="INCOMING",
                text=(
                    "Obrigado pelas orientações, mas ainda não consegui concluir e estou ficando frustrado. "
                    "Quero falar com um atendente humano agora, por favor."
                ),
                message_id="event-message-6",
            ),
        ],
    )
    triage = TriageDecision(
        rota="ESCALAR_IMEDIATAMENTE",
        prioridade="MEDIA",
        sentimento="negativo",
        tags=["explicit_human_request"],
    )

    package = build_handoff_package(
        instance=instance,
        reason="User requested a human.",
        conversation_context=context,
        triage_decision=triage,
        ai_summary=(
            "### Como configurar os campos da inscrição\n"
            "1. Acesse o **Painel v2** e siga uma resposta longa que não deve ser copiada."
        ),
    )

    assert package["customer_tone"] == "Frustrado, porém cordial"
    assert package["customer_tone_context"] == (
        "O cliente relata dificuldade para concluir, mas mantém uma comunicação respeitosa."
    )
    summary = package["conversation_summary"]
    assert "ingresso pago para o evento de Natal" in summary
    assert "200 ingressos" in summary
    assert "PIX e cartão" in summary
    assert "dados da inscrição" in summary
    assert "envio automático" in summary
    assert "estorno" in summary
    assert "pediu continuidade com um atendente humano" in summary
    assert len(summary) <= 900
    assert "###" not in summary
    assert "**" not in summary
    assert "O Salomão já respondeu" not in summary

    next_step = package["recommended_next_step"]
    assert "configuração do ingresso" in next_step
    assert "formas de pagamento e período de vendas" in next_step
    assert "campos da inscrição e comunicação automática" in next_step
    assert "elegibilidade do estorno" in next_step
    assert "sem pedir" not in next_step

    observation = format_handoff_observation(package)
    assert "**Tom do cliente:** Frustrado, porém cordial" in observation
    assert "**Prioridade da triagem:** Média" in observation
    assert "_Observação interna gerada" not in observation
    assert "### Como configurar" not in observation


def test_handoff_observation_explains_unavailable_module_lookup() -> None:
    observation = format_handoff_observation(
        {
            "customer_tone": "Calmo/neutro",
            "conversation_summary": "O cliente pediu atendimento humano.",
            "recommended_next_step": "Assumir o atendimento.",
            "module_lookup_status": "provider_error",
            "module_lookup_message": "InRadar retornou HTTP 400.",
            "obtained_modules": [],
        }
    )

    assert "**Módulos obtidos:** InRadar retornou HTTP 400." in observation


@pytest.mark.django_db
def test_watchdog_marks_stuck_instances_retryable() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:stuck-1",
        hubspot_thread_id="stuck-1",
        state=ConversationInstance.State.TRIAGE_RUNNING,
        last_activity_at=timezone.now() - timedelta(minutes=30),
    )

    result = run_lifecycle_watchdog(limit=10, max_failures=3)

    instance.refresh_from_db()
    assert result.scanned == 1
    assert result.marked_retryable == 1
    assert instance.state == ConversationInstance.State.FAILED_RETRYABLE
    assert instance.failure_count == 1


@pytest.mark.django_db
def test_watchdog_terminalizes_exhausted_failure_without_handoff() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:stuck-2",
        hubspot_thread_id="stuck-2",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
        failure_count=2,
        last_activity_at=timezone.now() - timedelta(minutes=30),
    )

    result = run_lifecycle_watchdog(limit=10, max_failures=3)

    instance.refresh_from_db()
    assert result.scanned == 1
    assert result.marked_retryable == 0
    assert result.marked_terminal == 1
    assert instance.state == ConversationInstance.State.FAILED_TERMINAL
    assert instance.failure_count == 3
    assert instance.next_retry_at is None


@pytest.mark.django_db
def test_watchdog_supersedes_placeholder_when_canonical_thread_exists() -> None:
    canonical = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:watchdog-thread",
        hubspot_thread_id="watchdog-thread",
        hubspot_ticket_id="watchdog-ticket",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        last_activity_at=timezone.now(),
    )
    placeholder = ConversationInstance.objects.create(
        idempotency_key="conversation:ticket:watchdog-ticket",
        hubspot_ticket_id="watchdog-ticket",
        state=ConversationInstance.State.CONTEXT_HYDRATING,
        last_activity_at=timezone.now() - timedelta(minutes=30),
    )

    result = run_lifecycle_watchdog(limit=10, max_failures=3)

    placeholder.refresh_from_db()
    assert result.marked_terminal == 1
    assert placeholder.state == ConversationInstance.State.IGNORED
    assert placeholder.failure_count == 0
    assert placeholder.metadata["identity_supersession"]["canonical_instance_id"] == str(canonical.pk)


@pytest.mark.django_db
def test_waiting_reconciliation_batch_balances_recent_and_starvation_safe_work() -> None:
    now = timezone.now()
    oldest = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:waiting-oldest",
        hubspot_thread_id="waiting-oldest",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        last_activity_at=now - timedelta(hours=8),
    )
    middle = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:waiting-middle",
        hubspot_thread_id="waiting-middle",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        last_activity_at=now - timedelta(hours=1),
    )
    newest = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:waiting-newest",
        hubspot_thread_id="waiting-newest",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        last_activity_at=now,
    )
    ConversationInstance.objects.filter(pk=oldest.pk).update(updated_at=now - timedelta(hours=10))
    ConversationInstance.objects.filter(pk=middle.pk).update(updated_at=now - timedelta(minutes=10))

    selected = waiting_customer_instances(limit=2)

    assert [instance.pk for instance in selected] == [newest.pk, oldest.pk]


@pytest.mark.django_db
def test_waiting_message_reconciliation_recovers_missed_customer_turn_once() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:missed-customer-turn",
        hubspot_thread_id="missed-customer-turn",
        hubspot_ticket_id="ticket-missed",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        last_message_id="incoming-1",
        last_activity_at=timezone.now(),
    )
    context = {
        "ticket_id": "ticket-missed",
        "pipeline": "636594474",
        "pipeline_stage": "939271304",
        "owner_id": "",
        "originating_channel": "1000",
        "contact_ids": ["contact-1"],
        "errors": [],
        "conversation_history": [
            {
                "id": "incoming-1",
                "thread_id": "missed-customer-turn",
                "direction": "INCOMING",
                "text": "Pergunta inicial",
                "created_at": "2026-07-29T12:00:00Z",
            },
            {
                "id": "outgoing-1",
                "thread_id": "missed-customer-turn",
                "direction": "OUTGOING",
                "text": "Resposta do Salomão",
                "created_at": "2026-07-29T12:01:00Z",
                "senders": [{"actorId": "A-81908844"}],
            },
            {
                "id": "incoming-2",
                "thread_id": "missed-customer-turn",
                "direction": "INCOMING",
                "text": "Resposta rápida que perdeu o webhook",
                "created_at": "2026-07-29T12:01:03Z",
            },
        ],
    }

    with (
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch("apps.ai_agents.tasks.schedule_salomao_thread_customer_turn") as schedule,
    ):
        result = reconcile_waiting_customer_messages(limit=10)
        duplicate = reconcile_waiting_customer_messages(limit=10)

    instance.refresh_from_db()
    assert result.scanned == 1
    assert result.recovered == 1
    assert result.failed == 0
    assert duplicate.scanned == 0
    assert instance.state == ConversationInstance.State.CONTEXT_HYDRATING
    assert instance.last_message_id == "incoming-2"
    assert instance.metadata["waiting_message_reconciliation"]["outcome"] == "customer_turn_recovered"
    event = ConversationEvent.objects.get(source="hubspot_reconciliation")
    assert event.idempotency_key == "reconciled-message:v1:missed-customer-turn:incoming-2"
    assert event.payload["detectedBy"] == "waiting_customer_reconciliation"
    schedule.assert_called_once_with("missed-customer-turn")


@pytest.mark.django_db
def test_waiting_message_reconciliation_does_not_repeat_processed_turn() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:unchanged-customer-turn",
        hubspot_thread_id="unchanged-customer-turn",
        hubspot_ticket_id="ticket-unchanged",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        last_message_id="incoming-1",
        last_activity_at=timezone.now(),
    )
    context = {
        "ticket_id": "ticket-unchanged",
        "pipeline": "636594474",
        "pipeline_stage": "939271304",
        "owner_id": "",
        "originating_channel": "1000",
        "errors": [],
        "conversation_history": [
            {
                "id": "incoming-1",
                "direction": "INCOMING",
                "text": "Já processada",
                "created_at": "2026-07-29T12:00:00Z",
            }
        ],
    }

    with (
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch("apps.ai_agents.tasks.schedule_salomao_thread_customer_turn") as schedule,
    ):
        result = reconcile_waiting_customer_messages(limit=10)

    instance.refresh_from_db()
    assert result.unchanged == 1
    assert result.recovered == 0
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert ConversationEvent.objects.count() == 0
    schedule.assert_not_called()


@pytest.mark.django_db
def test_stale_turn_followup_is_exactly_once_per_customer_message() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:stale-followup",
        hubspot_thread_id="stale-followup",
        hubspot_ticket_id="stale-ticket",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
    )
    reply_result = {
        "reason": "customer_turn_changed",
        "current_thread_id": "stale-followup",
        "current_customer_turn_id": "message-2",
    }

    with patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.apply_async") as enqueue:
        first = schedule_stale_turn_followup(
            instance=instance,
            context={"_stale_turn_followup_depth": 0},
            reply_result=reply_result,
            agent_run=None,
        )
        duplicate = schedule_stale_turn_followup(
            instance=instance,
            context={"_stale_turn_followup_depth": 0},
            reply_result=reply_result,
            agent_run=None,
        )

    assert first is True
    assert duplicate is False
    enqueue.assert_called_once_with(
        args=("stale-followup",),
        kwargs={"stale_turn_followup_depth": 1},
        countdown=1,
    )

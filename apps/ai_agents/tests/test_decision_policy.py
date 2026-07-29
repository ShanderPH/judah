"""Tests for deterministic Supervisor decision safety."""

import pytest

from apps.ai_agents.contracts import SupervisorDecision
from apps.ai_agents.services.decision_policy import (
    customer_input_signals,
    enforce_resolution_semantics,
    resolution_evidence_signals,
)


def test_customer_input_policy_ignores_question_heading_when_answer_is_conclusive() -> None:
    response = "## O que fazer?\n\n1. Acesse **Eventos**.\n2. Salve a configuração.\n\nConfiguração concluída."

    assert customer_input_signals(response) == []
    decision = SupervisorDecision(
        outcome="candidate_resolved",
        final_response=response,
        confidence=0.9,
    )
    assert enforce_resolution_semantics(decision) is decision


def test_customer_input_policy_downgrades_open_question_and_print_request() -> None:
    response = "Para eu continuar a análise, me informe a mensagem de erro e envie um print. Pode ser?"
    decision = SupervisorDecision(
        outcome="candidate_resolved",
        final_response=response,
        confidence=0.9,
    )

    normalized = enforce_resolution_semantics(decision)

    assert normalized.outcome == "waiting_customer"
    assert customer_input_signals(response) == [
        "open_question",
        "additional_customer_data_requested",
    ]
    assert "candidate_resolution_requires_customer_input" in normalized.risk_flags
    assert "resolution_policy: downgraded_to_waiting_customer" in normalized.trace_summary


def test_customer_input_policy_detects_request_before_trailing_source_block() -> None:
    response = (
        "Para confirmar o cenário, me informe em qual etapa aparece o erro e envie um print.\n\n"
        "Fonte: documentação de Eventos."
    )

    assert customer_input_signals(response) == ["additional_customer_data_requested"]


def test_customer_input_policy_does_not_change_non_candidate_outcomes() -> None:
    decision = SupervisorDecision(
        outcome="waiting_customer",
        final_response="Qual mensagem apareceu?",
        confidence=0.9,
    )

    assert enforce_resolution_semantics(decision) is decision


def test_customer_input_policy_keeps_audio_request_open() -> None:
    response = (
        "Pode mandar sim — se o canal permitir anexar áudio por aqui.\n\n"
        "No áudio, mencione qual é o problema e em qual módulo ou tela da InChurch ele acontece. "
        "Se aparecer erro na tela, um print junto também ajuda bastante."
    )
    decision = SupervisorDecision(
        outcome="candidate_resolved",
        final_response=response,
        confidence=0.86,
    )

    normalized = enforce_resolution_semantics(decision)

    assert normalized.outcome == "waiting_customer"
    assert customer_input_signals(response) == ["additional_customer_data_requested"]
    assert resolution_evidence_signals(response) == []
    assert "candidate_resolution_requires_customer_input" in normalized.risk_flags


def test_candidate_resolution_requires_positive_resolution_evidence() -> None:
    decision = SupervisorDecision(
        outcome="candidate_resolved",
        final_response="Entendi o cenário e vou te ajudar com isso.",
        confidence=0.99,
    )

    normalized = enforce_resolution_semantics(decision)

    assert normalized.outcome == "waiting_customer"
    assert "candidate_resolution_lacks_positive_evidence" in normalized.risk_flags
    assert "resolution_policy: no_positive_resolution_evidence" in normalized.trace_summary


@pytest.mark.parametrize(
    "response",
    [
        "Configure novamente e me avise se funcionar.",
        "Clique em Salvar e me retorne com o resultado.",
        "Configure a integração e confirme se deu certo.",
        "1. Acesse Eventos.\n2. Salve.\n\nSe não funcionar, me avise.",
        "Faça o teste e nos dê um retorno.",
        "Aguardo seu retorno.",
    ],
)
def test_candidate_resolution_keeps_future_customer_feedback_open(response: str) -> None:
    decision = SupervisorDecision(
        outcome="candidate_resolved",
        final_response=response,
        confidence=0.9,
    )

    normalized = enforce_resolution_semantics(decision)

    assert normalized.outcome == "waiting_customer"
    assert "additional_customer_data_requested" in customer_input_signals(response)
    assert "candidate_resolution_requires_customer_input" in normalized.risk_flags

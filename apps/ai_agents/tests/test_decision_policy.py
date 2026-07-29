"""Tests for deterministic Supervisor decision safety."""

from apps.ai_agents.contracts import SupervisorDecision
from apps.ai_agents.services.decision_policy import customer_input_signals, enforce_resolution_semantics


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

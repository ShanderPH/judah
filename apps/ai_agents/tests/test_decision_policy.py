from apps.ai_agents.services.decision_policy import customer_input_signals, resolution_evidence_signals


def test_response_signals_detect_customer_input() -> None:
    assert "open_question" in customer_input_signals("Pode enviar uma captura?")


def test_response_signals_detect_actionable_steps() -> None:
    assert "procedural_steps" in resolution_evidence_signals("1. Acesse o painel\n2. Salve a configuracao")

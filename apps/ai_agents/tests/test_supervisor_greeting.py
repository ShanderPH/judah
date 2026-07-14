"""Regression tests for the Supervisor first-message greeting invariant."""

from __future__ import annotations

from typing import Any, ClassVar

from django.test import override_settings

from apps.ai_agents.agents.supervisor import (
    FIRST_MESSAGE_GREETING,
    SalomaoResponse,
    SalomaoSupervisorAgent,
    _is_greeting_only,
)
from apps.ai_agents.contracts import SalomaoChatDraft, TriageDecision
from apps.ai_agents.models import TokenTrackingLog


class FakeLogger:
    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def error(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class FakeQuery:
    def __init__(self, *, message_count: int) -> None:
        self.message_count = message_count

    def aggregate(self, **_kwargs: Any) -> dict[str, int]:
        return {"total": 0}

    def count(self) -> int:
        return self.message_count


class FakeTokenTrackingManager:
    def __init__(self, *, message_count: int) -> None:
        self.message_count = message_count

    def filter(self, **_kwargs: Any) -> FakeQuery:
        return FakeQuery(message_count=self.message_count)


class FakeTeamResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.metrics = {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}
        self.member_responses: list[Any] = []
        self.messages: list[Any] = []


class FakeTeam:
    last_members: ClassVar[list[Any]] = []

    def __init__(self, content: str) -> None:
        self.content = content
        self.instructions: list[str] = []
        self.model = None

    def run(self, message: str, *, stream: bool) -> FakeTeamResponse:
        assert message == "Preciso de ajuda"
        assert stream is False
        return FakeTeamResponse(self.content)


class FakeConstructedTeam(FakeTeam):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("Team response")
        self.kwargs = kwargs
        self.instructions = kwargs.get("instructions", [])
        FakeTeam.last_members = kwargs.get("members", [])


class FakeTriageAgent:
    def __init__(self, **_kwargs: Any) -> None:
        pass


class FakeRagAgent:
    def __init__(self, **_kwargs: Any) -> None:
        pass


class FakeActionAgent:
    def __init__(self, **_kwargs: Any) -> None:
        pass


class FakeSalomaoChatAgent:
    def __init__(self, **_kwargs: Any) -> None:
        pass


class FakeTriageRunner:
    def __init__(self, decision: TriageDecision) -> None:
        self.decision = decision

    def run(self, _message: str) -> TriageDecision:
        return self.decision


class RaisingSalomaoChat:
    def create_chat_draft(self, **_kwargs: Any) -> SalomaoChatDraft:
        raise AssertionError("Salomao v1 must not be called for mandatory handoff")


class FailingTriageRunner:
    def run(self, _message: str) -> TriageDecision:
        raise RuntimeError("triage unavailable")


def _supervisor(
    *,
    team_content: str = "Como posso ajudar?",
    deterministic_response: SalomaoResponse | None = None,
) -> SalomaoSupervisorAgent:
    instance = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    instance.session_id = "session-1"
    instance.user_metadata = {}
    instance._logger = FakeLogger()
    instance._team = FakeTeam(team_content)
    instance._run_integrated_chain = lambda _message: deterministic_response
    return instance


def _response(message: str, *, requires_handoff: bool = False) -> SalomaoResponse:
    return SalomaoResponse(
        session_id="session-1",
        message=message,
        sources=[],
        requires_human_handoff=requires_handoff,
        handoff_reason="adapter failure" if requires_handoff else None,
        agent_trace=["salomao_chat: OK"],
        tokens_used=0,
        prompt_tokens=0,
        completion_tokens=0,
        model_name="salomao_v1",
        latency_ms=0,
    )


def _set_message_count(monkeypatch: Any, message_count: int) -> None:
    monkeypatch.setattr(
        TokenTrackingLog,
        "objects",
        FakeTokenTrackingManager(message_count=message_count),
    )


def _critical_triage() -> TriageDecision:
    return TriageDecision(
        rota="DUVIDAS_PLATAFORMA",
        prioridade="CRITICA",
        tags=[],
        dados_faltantes=[],
        sentimento="negativo",
    )


def test_first_message_standard_team_path_adds_required_greeting(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 0)

    response = _supervisor(team_content="Claro, vou te ajudar.").run_pipeline("Preciso de ajuda")

    assert response.message.startswith(FIRST_MESSAGE_GREETING)
    assert "Claro, vou te ajudar." in response.message


def test_first_message_salomao_deterministic_path_adds_required_greeting(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 0)
    supervisor = _supervisor(deterministic_response=_response("Resposta do Salomao v1."))

    response = supervisor.run_pipeline("Preciso de ajuda")

    assert response.message.startswith(FIRST_MESSAGE_GREETING)
    assert "Resposta do Salomao v1." in response.message


def test_later_message_standard_team_path_does_not_repeat_greeting(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 1)

    response = _supervisor(team_content="Continuando o atendimento.").run_pipeline("Preciso de ajuda")

    assert response.message == "Continuando o atendimento."


def test_later_message_salomao_deterministic_path_does_not_repeat_greeting(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 2)
    supervisor = _supervisor(deterministic_response=_response("Continuando via v1."))

    response = supervisor.run_pipeline("Preciso de ajuda")

    assert response.message == "Continuando via v1."


def test_first_message_salomao_fallback_handoff_still_gets_required_greeting(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 0)
    supervisor = _supervisor(
        deterministic_response=_response(
            "O atendimento com IA esta indisponivel no momento. Vou encaminhar para um atendente humano.",
            requires_handoff=True,
        )
    )

    response = supervisor.run_pipeline("Preciso de ajuda")

    assert response.requires_human_handoff is True
    assert response.message.startswith(FIRST_MESSAGE_GREETING)


def test_first_message_does_not_duplicate_existing_greeting(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 0)
    supervisor = _supervisor(team_content=f"{FIRST_MESSAGE_GREETING}\n\nComo posso ajudar?")

    response = supervisor.run_pipeline("Preciso de ajuda")

    assert response.message.count(FIRST_MESSAGE_GREETING) == 1


def test_final_response_is_guarded_and_has_structured_supervisor_decision(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 1)
    supervisor = _supervisor(deterministic_response=_response("O CPF informado foi 123.456.789-00."))

    response = supervisor.run_pipeline("Pode confirmar meus dados?")

    assert "123.456.789-00" not in response.message
    assert "cpf_redacted" in response.risk_flags
    assert response.supervisor_decision is not None
    assert response.supervisor_decision.outcome == "waiting_customer"
    assert response.supervisor_decision.final_response == response.message


@override_settings(SALOMAO_V1_BASE_URL="http://salomao.local", SALOMAO_V1_AS_TEAM_AGENT=True)
def test_salomao_v1_team_agent_is_enabled_when_base_url_is_configured() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)

    assert supervisor._should_enable_salomao_chat_agent() is True


@override_settings(SALOMAO_V1_BASE_URL="", SALOMAO_V1_AS_TEAM_AGENT=True)
def test_salomao_v1_team_agent_is_disabled_without_base_url() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)

    assert supervisor._should_enable_salomao_chat_agent() is False


@override_settings(SALOMAO_V1_BASE_URL="", SALOMAO_V1_AS_TEAM_AGENT=True)
def test_fallback_team_keeps_knowledge_rag_member(monkeypatch: Any) -> None:
    monkeypatch.setattr("apps.ai_agents.agents.supervisor.Team", FakeConstructedTeam)
    monkeypatch.setattr("apps.ai_agents.agents.supervisor.HeimdallTriageAgent", FakeTriageAgent)
    monkeypatch.setattr("apps.ai_agents.agents.supervisor.KnowledgeRagAgent", FakeRagAgent)
    monkeypatch.setattr("apps.ai_agents.agents.supervisor.HelpdeskActionAgent", FakeActionAgent)
    monkeypatch.setattr("apps.ai_agents.agents.supervisor.build_primary_model", lambda: object())
    monkeypatch.setattr("apps.ai_agents.agents.supervisor._build_fallback_config", lambda: None)
    monkeypatch.setattr("apps.ai_agents.agents.supervisor._build_redis_db", lambda _session_id: object())

    SalomaoSupervisorAgent(session_id="session-1", user_metadata={})

    assert any(isinstance(member, FakeRagAgent) for member in FakeTeam.last_members)


def test_integrated_chain_forces_handoff_for_critical_triage() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._triage = FakeTriageRunner(_critical_triage())
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor._run_integrated_chain("Sistema fora do ar")

    assert response is not None
    assert response.requires_human_handoff is True
    assert response.handoff_reason == "Heimdall classified the ticket as CRITICA."
    assert "supervisor: mandatory_human_handoff" in response.agent_trace
    assert "sinto muito pelo transtorno" in response.message
    assert "pessoa do nosso time" in response.message


def test_integrated_chain_forces_handoff_for_high_priority() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._triage = FakeTriageRunner(
        TriageDecision(
            rota="EVENTOS",
            prioridade="ALTA",
            tags=[],
            dados_faltantes=[],
            sentimento="neutro",
        )
    )
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor._run_integrated_chain("Meu evento está indisponível")

    assert response is not None
    assert response.requires_human_handoff is True
    assert response.handoff_reason == "Heimdall classified the ticket as ALTA."
    assert response.message.startswith("Sinto muito pelo transtorno.")


def test_integrated_chain_forces_handoff_for_customer_frustration() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._triage = FakeTriageRunner(
        TriageDecision(
            rota="DUVIDAS_PLATAFORMA",
            prioridade="MEDIA",
            tags=[],
            dados_faltantes=[],
            sentimento="negativo",
        )
    )
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor._run_integrated_chain("Já tentei várias vezes e não funciona")

    assert response is not None
    assert response.requires_human_handoff is True
    assert response.handoff_reason == "Heimdall detected customer frustration."
    assert response.message.startswith("Entendo como essa situação é frustrante")


def test_integrated_chain_asks_for_missing_data_before_calling_salomao() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._triage = FakeTriageRunner(
        TriageDecision(
            rota="SUPORTE_TECNICO_N1",
            prioridade="MEDIA",
            tags=["erro_evento"],
            dados_faltantes=["id_da_igreja"],
            sentimento="neutro",
            confidence=0.91,
        )
    )
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor._run_integrated_chain("Não aparece o campo telefone")

    assert response is not None
    assert response.outcome == "waiting_customer"
    assert response.requires_human_handoff is False
    assert response.missing_data == ["id_da_igreja"]
    assert "ID da igreja" in response.message


def test_greeting_only_messages_are_detected_without_swallowing_requests() -> None:
    assert _is_greeting_only("Oi!") is True
    assert _is_greeting_only("Olá, tudo bem?") is True
    assert _is_greeting_only("Boa tarde") is True
    assert _is_greeting_only("Oi, não consigo emitir um boleto") is False


def test_integrated_chain_asks_customer_need_for_greeting_instead_of_handoff() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._triage = FakeTriageRunner(
        TriageDecision(
            rota="ATENDIMENTO_IA",
            prioridade="MEDIA",
            tags=[],
            dados_faltantes=[],
            sentimento="neutro",
            confidence=0.2,
        )
    )
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor._run_integrated_chain("Oi!")

    assert response is not None
    assert response.outcome == "waiting_customer"
    assert response.requires_human_handoff is False
    assert response.missing_data == ["descricao_da_solicitacao"]
    assert "Como posso ajudar?" in response.message
    assert "supervisor: greeting_clarification" in response.agent_trace


def test_first_greeting_runs_full_pipeline_with_intro_and_clarification(monkeypatch: Any) -> None:
    _set_message_count(monkeypatch, 0)
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._team = FakeTeam("unused")
    supervisor._triage = FakeTriageRunner(
        TriageDecision(
            rota="ATENDIMENTO_IA",
            prioridade="MEDIA",
            tags=[],
            dados_faltantes=[],
            sentimento="neutro",
            confidence=0.2,
        )
    )
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor.run_pipeline("Oi!")

    assert response.message.startswith(FIRST_MESSAGE_GREETING)
    assert "Como posso ajudar?" in response.message
    assert response.outcome == "waiting_customer"
    assert response.requires_human_handoff is False


def test_integrated_chain_hands_off_when_heimdall_fails() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._triage = FailingTriageRunner()
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor._run_integrated_chain("Preciso de ajuda")

    assert response is not None
    assert response.outcome == "escalate_human"
    assert response.confidence == 0.0
    assert response.requires_human_handoff is True


@override_settings(HEIMDALL_MIN_CONFIDENCE=0.65)
def test_integrated_chain_hands_off_low_confidence_triage() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    supervisor.user_metadata = {}
    supervisor._logger = FakeLogger()
    supervisor._triage = FakeTriageRunner(
        TriageDecision(
            rota="ATENDIMENTO_IA",
            prioridade="MEDIA",
            sentimento="neutro",
            confidence=0.4,
        )
    )
    supervisor._salomao_chat = RaisingSalomaoChat()

    response = supervisor._run_integrated_chain("Não sei explicar o que aconteceu")

    assert response is not None
    assert response.outcome == "escalate_human"
    assert response.handoff_reason == "Heimdall confidence 0.40 is below policy threshold."


def test_salomao_draft_tokens_are_propagated_to_response() -> None:
    supervisor = SalomaoSupervisorAgent.__new__(SalomaoSupervisorAgent)
    supervisor.session_id = "session-1"
    draft = SalomaoChatDraft(
        response_text="Resposta do v1.",
        confidence=0.8,
        resolved=True,
        requires_human_handoff=False,
        prompt_tokens=11,
        completion_tokens=13,
        total_tokens=24,
        model_name="gpt-4o-mini",
    )

    response = supervisor._response_from_salomao_draft(draft, ["salomao_chat: OK"])

    assert response.prompt_tokens == 11
    assert response.completion_tokens == 13
    assert response.tokens_used == 24
    assert response.model_name == "gpt-4o-mini"

"""Tests for ai_agents Django models — exercises ORM fields and __str__."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.ai_agents.models import AgentMemory, AgentSession, AgentTrace, TokenTrackingLog


@pytest.mark.django_db
class TestAgentSession:
    def test_defaults(self) -> None:
        session = AgentSession.objects.create(session_id="sess-1")
        assert session.agent_type == AgentSession.AgentType.SALOMAO
        assert session.is_active is True
        assert session.ended_at is None

    def test_str_contains_identifiers(self) -> None:
        session = AgentSession.objects.create(session_id="sess-2", agent_type="heimdall")
        assert "heimdall" in str(session)
        assert "sess-2" in str(session)

    def test_unique_session_id(self) -> None:
        AgentSession.objects.create(session_id="sess-unique")
        with pytest.raises(Exception):  # noqa: B017 — IntegrityError is DB-dependent.
            AgentSession.objects.create(session_id="sess-unique")


@pytest.mark.django_db
class TestAgentMemory:
    def test_create_and_str(self) -> None:
        session = AgentSession.objects.create(session_id="sess-mem")
        memory = AgentMemory.objects.create(session=session, key="fav_color", value="red")
        assert "sess-mem" in str(memory)
        assert "fav_color" in str(memory)

    def test_unique_key_per_session(self) -> None:
        session = AgentSession.objects.create(session_id="sess-dup")
        AgentMemory.objects.create(session=session, key="k", value="v1")
        with pytest.raises(Exception):  # noqa: B017
            AgentMemory.objects.create(session=session, key="k", value="v2")


@pytest.mark.django_db
class TestAgentTrace:
    def test_user_role(self) -> None:
        session = AgentSession.objects.create(session_id="sess-trace")
        trace = AgentTrace.objects.create(
            session=session,
            role=AgentTrace.Role.USER,
            content="hello",
        )
        assert trace.role == "user"
        assert trace.tokens_used == 0

    def test_tool_role_with_metadata(self) -> None:
        session = AgentSession.objects.create(session_id="sess-tool")
        trace = AgentTrace.objects.create(
            session=session,
            role=AgentTrace.Role.TOOL,
            content="search results",
            tool_name="knowledge_search",
            tool_input={"query": "pricing"},
            tool_output={"hits": 3},
            tokens_used=120,
            latency_ms=450,
        )
        assert trace.tool_name == "knowledge_search"
        assert trace.tool_input == {"query": "pricing"}
        assert "tool" in str(trace)


@pytest.mark.django_db
class TestTokenTrackingLog:
    def test_create_with_cost(self) -> None:
        log = TokenTrackingLog.objects.create(
            session_id="sess-cost",
            ticket_id="12345",
            model_name="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            total_cost_usd=Decimal("0.001250"),
        )
        assert log.prompt_tokens == 100
        assert log.total_cost_usd == Decimal("0.001250")

    def test_str_contains_model_and_cost(self) -> None:
        log = TokenTrackingLog.objects.create(
            session_id="sess-str",
            model_name="gpt-4o-mini",
            total_cost_usd=Decimal("0.000500"),
        )
        rendered = str(log)
        assert "gpt-4o-mini" in rendered
        assert "0.000500" in rendered

    def test_nullable_ticket_id(self) -> None:
        log = TokenTrackingLog.objects.create(
            session_id="sess-no-ticket",
            model_name="gpt-4o",
        )
        assert log.ticket_id is None

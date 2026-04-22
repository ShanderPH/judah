"""Unit tests for AI-agent Ninja schemas (pydantic validation)."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.ai_agents.schemas import (
    ChatRequest,
    ChatResponse,
    SessionResponse,
    TriageRequest,
    TriageResult,
)


class TestChatRequest:
    def test_minimal_payload_uses_defaults(self) -> None:
        req = ChatRequest(message="oi")
        assert req.message == "oi"
        assert req.session_id is None
        assert req.agent_type == "salomao"
        assert req.channel == "api"

    def test_full_payload_accepted(self) -> None:
        req = ChatRequest(
            message="ajuda",
            session_id="user-1",
            agent_type="heimdall",
            channel="whatsapp",
            user_identifier="user-1@inchurch.com",
            church_external_id="ch-42",
            hubspot_contact_id="1001",
        )
        assert req.agent_type == "heimdall"
        assert req.hubspot_contact_id == "1001"


class TestChatResponse:
    def test_defaults(self) -> None:
        resp = ChatResponse(session_id="s1", message="ok", agent_type="salomao")
        assert resp.sources == []
        assert resp.tokens_used == 0
        assert resp.latency_ms == 0

    def test_sources_populated(self) -> None:
        resp = ChatResponse(
            session_id="s1",
            message="ok",
            agent_type="salomao",
            sources=[{"title": "article 1"}],
            tokens_used=42,
            latency_ms=120,
        )
        assert resp.tokens_used == 42
        assert resp.sources[0]["title"] == "article 1"


class TestTriageRequest:
    def test_defaults(self) -> None:
        req = TriageRequest(message="oi")
        assert req.channel == "whatsapp"
        assert req.user_identifier == ""


class TestTriageResult:
    def test_full_result(self) -> None:
        res = TriageResult(
            intent="support",
            confidence=0.87,
            suggested_queue="billing",
            suggested_priority="high",
            requires_human=True,
            reasoning="User explicitly asked for human.",
        )
        assert res.intent == "support"
        assert res.requires_human is True

    def test_defaults(self) -> None:
        res = TriageResult(intent="chat", confidence=0.5)
        assert res.requires_human is False
        assert res.suggested_priority == "medium"
        assert res.suggested_queue is None


class TestSessionResponse:
    def test_from_attrs_friendly_payload(self) -> None:
        now = datetime.now(tz=UTC)
        res = SessionResponse(
            session_id="s1",
            agent_type="salomao",
            channel="api",
            is_active=True,
            created_at=now,
        )
        assert res.session_id == "s1"
        assert res.is_active is True
        assert res.created_at == now

"""Network-isolated tests for the HubSpot FastMCP tools."""

import httpx
import pytest

from apps.ai_agents.mcp_servers import hubspot_server

RealAsyncClient = httpx.AsyncClient


@pytest.fixture(autouse=True)
def hubspot_environment(monkeypatch):
    values = {
        "HUBSPOT_ACCESS_TOKEN": "token",
        "HUBSPOT_PORTAL_ID": "portal",
        "HUBSPOT_DEFAULT_TICKET_PIPELINE_ID": "pipeline",
        "HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID": "new",
        "HUBSPOT_SUPPORT_NEW_STAGE_ID": "support-new",
        "HUBSPOT_DEFAULT_TICKET_OPEN_STAGE_ID": "open",
        "HUBSPOT_DEFAULT_TICKET_WAITING_STAGE_ID": "waiting",
        "HUBSPOT_DEFAULT_TICKET_CLOSED_STAGE_ID": "closed",
        "HUBSPOT_SUPPORT_CLOSED_STAGE_ID": "support-closed",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _patch_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        hubspot_server.httpx,
        "AsyncClient",
        lambda **kwargs: RealAsyncClient(transport=transport, timeout=kwargs.get("timeout")),
    )


def test_mcp_environment_helpers(monkeypatch) -> None:
    assert hubspot_server._pipeline_id("HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID") == "new"
    assert hubspot_server._get_hubspot_token() == "token"
    assert hubspot_server._build_headers()["Authorization"] == "Bearer token"
    assert hubspot_server._get_portal_id() == "portal"
    assert hubspot_server._map_stage_to_status("waiting") == "waiting"
    assert hubspot_server._map_stage_to_status("missing") == "unknown"

    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN")
    with pytest.raises(RuntimeError):
        hubspot_server._get_hubspot_token()
    monkeypatch.delenv("HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID")
    with pytest.raises(RuntimeError):
        hubspot_server._pipeline_id("HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID")


@pytest.mark.asyncio
async def test_get_ticket_status_success(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "ticket-1",
                "properties": {
                    "subject": "Falha",
                    "content": "Detalhes",
                    "hs_ticket_priority": "HIGH",
                    "hs_pipeline": "pipeline",
                    "hs_pipeline_stage": "open",
                    "hubspot_owner_id": "10",
                    "hs_ticket_category": "OTHER",
                },
            },
        )

    _patch_client(monkeypatch, handler)
    result = await hubspot_server.get_ticket_status("ticket-1")
    assert result["status"] == "open"
    assert result["subject"] == "Falha"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "message"),
    [(404, "não encontrado"), (401, "autenticação"), (429, "rate limit"), (500, "Erro HTTP 500")],
)
async def test_get_ticket_status_http_errors(monkeypatch, status_code: int, message: str) -> None:
    _patch_client(monkeypatch, lambda request: httpx.Response(status_code, text="error"))
    result = await hubspot_server.get_ticket_status("ticket-1")
    assert result["status_code"] == status_code
    assert message in result["error"]


@pytest.mark.asyncio
async def test_get_ticket_status_timeout_and_unexpected(monkeypatch) -> None:
    def timeout(request: httpx.Request):
        raise httpx.ReadTimeout("slow", request=request)

    _patch_client(monkeypatch, timeout)
    assert (await hubspot_server.get_ticket_status("ticket"))["status_code"] == 504

    def unexpected(request: httpx.Request):
        raise RuntimeError("broken")

    _patch_client(monkeypatch, unexpected)
    assert (await hubspot_server.get_ticket_status("ticket"))["status_code"] == 500


@pytest.mark.asyncio
async def test_create_ticket_with_contact_success(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contacts/search"):
            return httpx.Response(200, json={"results": [{"id": "contact-1"}]})
        body = request.content.decode()
        assert "contact-1" in body
        assert "URGENT" in body
        return httpx.Response(
            200,
            json={
                "id": "ticket-1",
                "properties": {
                    "subject": "Falha",
                    "content": "Falha",
                    "hs_ticket_priority": "URGENT",
                    "hs_pipeline_stage": "new",
                    "hs_pipeline": "pipeline",
                    "createdate": "now",
                },
            },
        )

    _patch_client(monkeypatch, handler)
    result = await hubspot_server.create_helpdesk_ticket("user@example.com", "Falha", urgency=1)
    assert result["id"] == "ticket-1"
    assert result["url"].endswith("/ticket/ticket-1/")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "message"),
    [(400, "Dados inválidos"), (401, "autenticação"), (409, "Conflito"), (429, "rate limit")],
)
async def test_create_ticket_http_errors(monkeypatch, status_code: int, message: str) -> None:
    _patch_client(monkeypatch, lambda request: httpx.Response(status_code, text="detail"))
    result = await hubspot_server.create_helpdesk_ticket("user-id", "Falha", urgency=99)
    assert result["status_code"] == status_code
    assert message in result["error"]


@pytest.mark.asyncio
async def test_create_ticket_timeout_and_unexpected(monkeypatch) -> None:
    def timeout(request: httpx.Request):
        raise httpx.ReadTimeout("slow", request=request)

    _patch_client(monkeypatch, timeout)
    assert (await hubspot_server.create_helpdesk_ticket("user", "Falha"))["status_code"] == 504

    def unexpected(request: httpx.Request):
        raise RuntimeError("broken")

    _patch_client(monkeypatch, unexpected)
    assert (await hubspot_server.create_helpdesk_ticket("user", "Falha"))["status_code"] == 500


@pytest.mark.asyncio
async def test_update_ticket_success_and_noop(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"id": "note-1"})

    _patch_client(monkeypatch, handler)
    result = await hubspot_server.update_ticket(
        "ticket-1",
        pipeline_stage="waiting",
        priority="HIGH",
        reply_note="Resposta",
        status_note_public=True,
    )
    assert result["stage_updated"] is True
    assert result["priority_updated"] is True
    assert result["note_created"] is True
    assert result["errors"] == []

    result = await hubspot_server.update_ticket("ticket-1")
    assert result["stage_updated"] is False
    assert result["note_created"] is False


@pytest.mark.asyncio
async def test_update_ticket_collects_http_and_transport_errors(monkeypatch) -> None:
    calls = 0

    def http_errors(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500 if calls == 1 else 400, text="error")

    _patch_client(monkeypatch, http_errors)
    result = await hubspot_server.update_ticket("ticket", pipeline_stage="open", reply_note="note")
    assert result["errors"] == ["patch_ticket:500", "create_note:400"]

    def transport_errors(request: httpx.Request):
        raise httpx.ConnectError("offline", request=request)

    _patch_client(monkeypatch, transport_errors)
    result = await hubspot_server.update_ticket("ticket", priority="HIGH", reply_note="note")
    assert result["errors"] == ["patch_ticket:ConnectError", "create_note:ConnectError"]


@pytest.mark.asyncio
async def test_resolve_contact_paths(monkeypatch) -> None:
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json={"results": [{"id": "contact"}]}))
    assert await hubspot_server._resolve_contact_by_email("a@example.com") == "contact"

    _patch_client(monkeypatch, lambda request: httpx.Response(200, json={"results": []}))
    assert await hubspot_server._resolve_contact_by_email("a@example.com") is None

    def failure(request: httpx.Request):
        raise RuntimeError("offline")

    _patch_client(monkeypatch, failure)
    assert await hubspot_server._resolve_contact_by_email("a@example.com") is None

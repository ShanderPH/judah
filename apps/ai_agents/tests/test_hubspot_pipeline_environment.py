from __future__ import annotations

import pytest

from apps.ai_agents.mcp_servers.hubspot_server import _map_stage_to_status, _pipeline_id


def test_pipeline_id_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_TEST_STAGE_ID", "custom-stage")

    assert _pipeline_id("HUBSPOT_TEST_STAGE_ID") == "custom-stage"


def test_pipeline_id_rejects_missing_required_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUBSPOT_TEST_STAGE_ID", raising=False)

    with pytest.raises(RuntimeError, match="HUBSPOT_TEST_STAGE_ID"):
        _pipeline_id("HUBSPOT_TEST_STAGE_ID")


def test_stage_status_map_uses_configured_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = {
        "HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID": "default-new",
        "HUBSPOT_SUPPORT_NEW_STAGE_ID": "support-new",
        "HUBSPOT_DEFAULT_TICKET_OPEN_STAGE_ID": "default-open",
        "HUBSPOT_DEFAULT_TICKET_WAITING_STAGE_ID": "default-waiting",
        "HUBSPOT_DEFAULT_TICKET_CLOSED_STAGE_ID": "default-closed",
        "HUBSPOT_SUPPORT_CLOSED_STAGE_ID": "support-closed",
    }
    for name, value in configured.items():
        monkeypatch.setenv(name, value)

    assert _map_stage_to_status("support-new") == "new"
    assert _map_stage_to_status("default-open") == "open"
    assert _map_stage_to_status("default-waiting") == "waiting"
    assert _map_stage_to_status("support-closed") == "closed"
    assert _map_stage_to_status("unmapped") == "unknown"

"""Gate B (BE-02) readiness tests: cycle posture exposed without PII.

The vendor-neutral ``_conversation_cycle_checks()`` section is exercised on
every lane; the full ``evaluate_assignment_readiness()`` path also runs on
PostgreSQL because its pre-existing introspection SQL is PostgreSQL-only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.support.assignment_readiness import (
    _conversation_cycle_checks,
    evaluate_assignment_readiness,
)
from apps.support.conversation_cycle_service import build_cycle_key
from apps.support.models import (
    Agent,
    AssignmentAttempt,
    AssignmentLog,
    NewConversation,
    SupportConversationCycle,
)

pytestmark = pytest.mark.django_db

PORTAL_VALUE = "portal-secret-99887766"
TICKET_ID = "ticket-pii-4455"
AGENT_EMAIL = "readiness-agent@example.test"
ENTRY_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _settings():
    with override_settings(HUBSPOT_PORTAL_ID=PORTAL_VALUE, CONVERSATION_CYCLES_ENFORCED=False):
        yield


def _agent() -> Agent:
    return Agent.objects.create(
        name="Readiness Agent",
        agent_email=AGENT_EMAIL,
        hubspot_owner_id=7001,
        status_enum=Agent.StatusEnum.ONLINE,
        is_active=True,
    )


def _cycle(ticket: str = TICKET_ID, state: str = SupportConversationCycle.State.QUEUED) -> SupportConversationCycle:
    return SupportConversationCycle.objects.create(
        cycle_key=build_cycle_key(
            source_system="hubspot",
            source_account_id=PORTAL_VALUE,
            hubspot_ticket_id=ticket,
            entered_stage_at=ENTRY_AT,
        ),
        source_account_id=PORTAL_VALUE,
        hubspot_ticket_id=ticket,
        entered_stage_at=ENTRY_AT,
        state=state,
        opened_at=ENTRY_AT,
    )


class TestConversationCycleChecks:
    def test_portal_and_enforcement_are_booleans_only(self) -> None:
        checks = _conversation_cycle_checks()
        assert checks["portal_configured"] is True
        assert checks["enforced"] is False
        assert checks["migration_applied"] is True
        assert PORTAL_VALUE not in json.dumps(checks)

    def test_missing_portal_is_boolean_false(self) -> None:
        with override_settings(HUBSPOT_PORTAL_ID=""):
            checks = _conversation_cycle_checks()
        assert checks["portal_configured"] is False

    def test_coverage_counts_rows_with_and_without_cycle(self) -> None:
        cycle = _cycle()
        now = timezone.now()
        NewConversation.objects.create(hubspot_ticket_id=TICKET_ID, entered_queue_at=now, cycle=cycle)
        NewConversation.objects.create(hubspot_ticket_id="other", entered_queue_at=now)
        agent = _agent()
        attempt = AssignmentAttempt.objects.create(
            idempotency_key="00000000-0000-0000-0000-0000000000aa",
            ticket_id=TICKET_ID,
            selected_agent=agent,
            eligibility_revision=1,
            desired_hubspot_owner_id=agent.hubspot_owner_id,
            decision_reason="eligible",
            reserved_at=now,
            cycle=cycle,
        )
        AssignmentLog.objects.create(ticket_id=TICKET_ID, agent_name=agent.name)

        checks = _conversation_cycle_checks()

        assert checks["total_cycles"] == 1
        assert checks["projection_coverage"]["new_conversations"] == {
            "total": 2,
            "with_cycle": 1,
            "null_cycle": 1,
            "ticket_mismatch": 0,
        }
        attempt_coverage = checks["projection_coverage"]["assignment_attempts"]
        assert attempt_coverage["with_cycle"] == 1
        assert attempt_coverage["null_cycle"] == 0
        assert checks["projection_coverage"]["assignment_logs"]["null_cycle"] == 1
        assert checks["projection_mismatches"] == 0
        assert checks["legacy_rows"] == 2
        assert checks["legacy_writers_detected"] is True
        assert checks["enforcement_ready"] is False
        assert attempt.cycle_id == cycle.pk

    def test_enforcement_ready_requires_dispatch_and_complete_coverage(self) -> None:
        cycle = _cycle()
        checks = _conversation_cycle_checks()
        assert checks["queued_without_dispatch"] == 1
        assert checks["enforcement_ready"] is False

        NewConversation.objects.create(
            hubspot_ticket_id=TICKET_ID,
            entered_queue_at=timezone.now(),
            cycle=cycle,
        )
        checks = _conversation_cycle_checks()
        assert checks["queued_without_dispatch"] == 0
        assert checks["legacy_rows"] == 0
        assert checks["enforcement_ready"] is True

    def test_projection_mismatch_is_counted(self) -> None:
        cycle = _cycle()
        NewConversation.objects.create(
            hubspot_ticket_id="different-ticket",
            entered_queue_at=timezone.now(),
            cycle=cycle,
        )
        checks = _conversation_cycle_checks()
        assert checks["projection_mismatches"] == 1

    def test_checks_contain_no_pii(self) -> None:
        cycle = _cycle()
        _agent()
        NewConversation.objects.create(
            hubspot_ticket_id=TICKET_ID,
            entered_queue_at=timezone.now(),
            cycle=cycle,
            contact_email=AGENT_EMAIL,
        )
        serialized = json.dumps(_conversation_cycle_checks())
        assert TICKET_ID not in serialized
        assert AGENT_EMAIL not in serialized
        assert PORTAL_VALUE not in serialized
        assert cycle.cycle_key not in serialized


class TestFullReadinessPath:
    @pytest.fixture(autouse=True)
    def _require_postgresql(self):
        if connection.vendor != "postgresql":
            pytest.skip("Full readiness path uses PostgreSQL-only introspection.")

    def test_cycle_section_is_embedded_and_mismatch_becomes_reason(self) -> None:
        cycle = _cycle()
        NewConversation.objects.create(
            hubspot_ticket_id="different-ticket",
            entered_queue_at=timezone.now(),
            cycle=cycle,
        )
        readiness = evaluate_assignment_readiness()
        assert readiness["checks"]["conversation_cycles"]["projection_mismatches"] == 1
        assert "conversation_cycle_projection_mismatch" in readiness["reasons"]
        assert PORTAL_VALUE not in json.dumps(readiness)

    def test_legacy_rows_and_missing_dispatch_are_rollout_reasons(self) -> None:
        _cycle()
        NewConversation.objects.create(
            hubspot_ticket_id="legacy-ticket",
            entered_queue_at=timezone.now(),
        )

        readiness = evaluate_assignment_readiness()

        assert "conversation_cycle_legacy_rows" in readiness["reasons"]
        assert "conversation_cycle_dispatch_missing" in readiness["reasons"]


def test_full_readiness_contract_without_postgresql_server(monkeypatch) -> None:
    """Exercise the complete readiness contract on the fast local test lane."""
    original_cursor = connection.cursor

    def portable_cursor(*args, **kwargs):
        real_cursor = original_cursor(*args, **kwargs)

        class CursorProxy:
            special_query = False

            def execute(self, sql, params=None):
                if str(sql).startswith("SELECT current_user"):
                    self.special_query = True
                    return None
                return real_cursor.execute(sql, params)

            def fetchone(self):
                if self.special_query:
                    return ("test-role", "judah:local-test:pytest")
                return real_cursor.fetchone()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                real_cursor.close()

            def __getattr__(self, name):
                return getattr(real_cursor, name)

        return CursorProxy()

    monkeypatch.setattr(connection, "cursor", portable_cursor)

    readiness = evaluate_assignment_readiness()

    assert readiness["state"] in {"healthy", "degraded", "unhealthy"}
    assert readiness["checks"]["writer_role"] == "test-role"
    assert readiness["checks"]["application_name_configured"] is True
    assert "conversation_cycles" in readiness["checks"]

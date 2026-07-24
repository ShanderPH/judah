"""Round-trip safety tests for conversation-instance identity migration."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATE_FROM = ("ai_agents", "0005_agent_run_versions")
MIGRATE_TO = ("ai_agents", "0006_remove_unique_conversation_instance_ticket")


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def test_multiple_ticket_instances_survive_reverse_and_reapply() -> None:
    executor = _migrate(MIGRATE_TO)
    current_apps = executor.loader.project_state([MIGRATE_TO]).apps
    conversation_instance = current_apps.get_model("ai_agents", "ConversationInstance")
    first = conversation_instance.objects.create(
        idempotency_key="migration-thread-first",
        hubspot_thread_id="migration-thread-first",
        hubspot_ticket_id="migration-ticket",
    )
    second = conversation_instance.objects.create(
        idempotency_key="migration-thread-second",
        hubspot_thread_id="migration-thread-second",
        hubspot_ticket_id="migration-ticket",
    )

    executor = _migrate(MIGRATE_FROM)
    old_apps = executor.loader.project_state([MIGRATE_FROM]).apps
    old_instance = old_apps.get_model("ai_agents", "ConversationInstance")
    rolled_back = list(old_instance.objects.filter(id__in=[first.pk, second.pk]).order_by("id"))
    assert len(rolled_back) == 2
    assert sum(row.hubspot_ticket_id == "migration-ticket" for row in rolled_back) == 1
    assert sum(row.hubspot_ticket_id is None for row in rolled_back) == 1

    executor = _migrate(MIGRATE_TO)
    reapplied_apps = executor.loader.project_state([MIGRATE_TO]).apps
    reapplied_instance = reapplied_apps.get_model("ai_agents", "ConversationInstance")
    restored = reapplied_instance.objects.filter(
        id__in=[first.pk, second.pk],
        hubspot_ticket_id="migration-ticket",
    )
    assert restored.count() == 2

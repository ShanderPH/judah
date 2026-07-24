"""Migration safety tests for legacy webhook uniqueness drift."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATE_FROM = ("webhooks", "0005_webhookevent_deduplication_key")
MIGRATE_TO = ("webhooks", "0006_drop_legacy_event_id_uniqueness")
LEGACY_INDEX = "legacy_webhook_event_id_uniq"


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def test_legacy_event_id_uniqueness_apply_reverse_reapply() -> None:
    executor = _migrate(MIGRATE_FROM)
    old_apps = executor.loader.project_state([MIGRATE_FROM]).apps
    webhook_event = old_apps.get_model("webhooks", "WebhookEvent")

    with connection.cursor() as cursor:
        cursor.execute(f"CREATE UNIQUE INDEX {connection.ops.quote_name(LEGACY_INDEX)} ON webhook_events (event_id)")

    _migrate(MIGRATE_TO)
    webhook_event.objects.create(event_type="unknown", event_id="reused", payload={})
    webhook_event.objects.create(event_type="unknown", event_id="reused", payload={})

    _migrate(MIGRATE_FROM)
    _migrate(MIGRATE_TO)

    assert webhook_event.objects.filter(event_id="reused").count() == 2

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.utils import timezone

QUEUE_TABLE = "new_conversations"
QUEUE_STATUS_CONSTRAINT = "new_conversations_queue_status_check"
LEGACY_PERIODIC_TASK = "support.task_requeue_stale_assignments"


def _constraint_definition(schema_editor: BaseDatabaseSchemaEditor) -> str:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = %s::regclass
              AND conname = %s
            """,
            [QUEUE_TABLE, QUEUE_STATUS_CONSTRAINT],
        )
        row = cursor.fetchone()
    return str(row[0]) if row else ""


def _replace_queue_status_constraint(
    schema_editor: BaseDatabaseSchemaEditor,
    *,
    include_failed: bool,
) -> None:
    quote = schema_editor.quote_name
    allowed = "'pending', 'queued', 'failed'" if include_failed else "'pending', 'queued'"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {quote(QUEUE_TABLE)} DROP CONSTRAINT IF EXISTS {quote(QUEUE_STATUS_CONSTRAINT)}")
        cursor.execute(
            f"ALTER TABLE {quote(QUEUE_TABLE)} "
            f"ADD CONSTRAINT {quote(QUEUE_STATUS_CONSTRAINT)} "
            f"CHECK (queue_status IN ({allowed})) NOT VALID"
        )
        cursor.execute(f"ALTER TABLE {quote(QUEUE_TABLE)} VALIDATE CONSTRAINT {quote(QUEUE_STATUS_CONSTRAINT)}")


def _set_legacy_periodic_task_enabled(
    apps: Apps,
    *,
    enabled: bool,
) -> None:
    periodic_task = apps.get_model("django_celery_beat", "PeriodicTask")
    periodic_tasks = apps.get_model("django_celery_beat", "PeriodicTasks")
    changed = periodic_task.objects.filter(task=LEGACY_PERIODIC_TASK).exclude(enabled=enabled).update(enabled=enabled)
    if changed:
        periodic_tasks.objects.update_or_create(
            ident=1,
            defaults={"last_update": timezone.now()},
        )


def repair_queue_contract(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    if schema_editor.connection.vendor == "postgresql":
        definition = _constraint_definition(schema_editor)
        if "'failed'" not in definition:
            _replace_queue_status_constraint(schema_editor, include_failed=True)
    _set_legacy_periodic_task_enabled(apps, enabled=False)


def restore_queue_contract(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    new_conversation = apps.get_model("support", "NewConversation")
    if new_conversation.objects.filter(queue_status="failed").exists():
        raise RuntimeError(
            "Cannot restore the legacy queue-status constraint while quarantined rows exist. "
            "Resolve or migrate those rows before rolling back support.0024."
        )
    if schema_editor.connection.vendor == "postgresql":
        definition = _constraint_definition(schema_editor)
        if "'failed'" in definition:
            _replace_queue_status_constraint(schema_editor, include_failed=False)
    _set_legacy_periodic_task_enabled(apps, enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("django_celery_beat", "0019_alter_periodictasks_options"),
        ("support", "0023_cycle_backfill_contract"),
    ]

    operations = [
        migrations.RunPython(
            repair_queue_contract,
            reverse_code=restore_queue_contract,
        ),
    ]

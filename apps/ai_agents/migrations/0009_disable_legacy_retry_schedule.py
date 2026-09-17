"""Disable the obsolete lifecycle retry schedule left in django-celery-beat."""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.utils import timezone

LEGACY_RETRY_SCHEDULE = "ai-lifecycle-retry-dispatch"
LEGACY_RETRY_TASK = "ai_agents.retry_failed_lifecycle_instances_task"


def disable_legacy_retry_schedule(
    apps: Apps,
    _schema_editor: BaseDatabaseSchemaEditor | None,
) -> None:
    """Disable only the exact obsolete schedule or task without deleting audit data."""
    periodic_task = apps.get_model("django_celery_beat", "PeriodicTask")
    periodic_tasks = apps.get_model("django_celery_beat", "PeriodicTasks")
    changed = periodic_task.objects.filter(
        models.Q(name=LEGACY_RETRY_SCHEDULE) | models.Q(task=LEGACY_RETRY_TASK),
        enabled=True,
    ).update(enabled=False)
    if changed:
        periodic_tasks.objects.update_or_create(
            ident=1,
            defaults={"last_update": timezone.now()},
        )


class Migration(migrations.Migration):
    """Repair persisted scheduler state after the legacy task was removed."""

    dependencies = [
        ("ai_agents", "0008_remove_legacy_identification_triage"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(
            disable_legacy_retry_schedule,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

"""Disable the legacy poll-hubspot-agent-status periodic task.

The SAT heartbeat (20-second interval) replaced this task. The old task
references ``support.task_poll_hubspot_agent_status`` which no longer exists,
causing silent failures on every execution.
"""

from django.db import migrations


def disable_legacy_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="poll-hubspot-agent-status").update(enabled=False)


def enable_legacy_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="poll-hubspot-agent-status").update(enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0010_add_business_hours_and_special_schedules"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(disable_legacy_task, enable_legacy_task),
    ]

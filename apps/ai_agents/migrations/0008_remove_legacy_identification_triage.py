"""Remove database-facing remnants of legacy identification and triage."""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.utils import timezone

LEGACY_STATES = (
    "CONTACT_REQUIRED",
    "CONTACT_COLLECTING",
    "CONTACT_ASSOCIATING",
    "TRIAGE_PENDING",
    "TRIAGE_RUNNING",
)
LEGACY_RETRY_SCHEDULE = "ai-lifecycle-retry-dispatch"
LEGACY_RETRY_TASK = "ai_agents.retry_failed_lifecycle_instances_task"

STATE_CHOICES = [
    ("RECEIVED", "Received"),
    ("NORMALIZED", "Normalized"),
    ("CONTEXT_HYDRATING", "Context Hydrating"),
    ("CONTEXT_READY", "Context Ready"),
    ("AI_SERVICE_PENDING", "AI Service Pending"),
    ("AI_SERVICE_RUNNING", "AI Service Running"),
    ("WAITING_FOR_CUSTOMER", "Waiting for Customer"),
    ("HUMAN_HANDOFF_REQUESTED", "Human Handoff Requested"),
    ("QUEUE_PENDING", "Queue Pending"),
    ("HUMAN_ASSIGNED", "Human Assigned"),
    ("HUMAN_IN_PROGRESS", "Human In Progress"),
    ("RESOLVED_BY_AI", "Resolved by AI"),
    ("RESOLVED_BY_HUMAN", "Resolved by Human"),
    ("CLOSED", "Closed"),
    ("FAILED_RETRYABLE", "Failed Retryable"),
    ("FAILED_TERMINAL", "Failed Terminal"),
    ("IGNORED", "Ignored"),
]


def assert_no_active_legacy_work(
    apps: Apps,
    _schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Stop before changing choices when legacy work is still active."""
    conversation_instance = apps.get_model("ai_agents", "ConversationInstance")
    agent_session = apps.get_model("ai_agents", "AgentSession")

    legacy_instances = conversation_instance.objects.filter(state__in=LEGACY_STATES).count()
    active_heimdall_sessions = agent_session.objects.filter(agent_type="heimdall", is_active=True).count()
    if legacy_instances or active_heimdall_sessions:
        raise RuntimeError(
            "Legacy identification/triage work is still active: "
            f"conversation_instances={legacy_instances}, "
            f"active_heimdall_sessions={active_heimdall_sessions}. "
            "Resolve these records before applying ai_agents.0008."
        )


def remove_legacy_retry_schedule(
    apps: Apps,
    _schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Delete only the exact obsolete Celery Beat schedule."""
    periodic_task = apps.get_model("django_celery_beat", "PeriodicTask")
    periodic_tasks = apps.get_model("django_celery_beat", "PeriodicTasks")
    deleted, _details = periodic_task.objects.filter(
        models.Q(name=LEGACY_RETRY_SCHEDULE) | models.Q(task=LEGACY_RETRY_TASK)
    ).delete()
    if deleted:
        periodic_tasks.objects.update_or_create(
            ident=1,
            defaults={"last_update": timezone.now()},
        )


class Migration(migrations.Migration):
    """Narrow legacy choices without deleting historical rows."""

    dependencies = [
        ("ai_agents", "0007_conversationservicecycle_agentrun_service_cycle_and_more"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(assert_no_active_legacy_work, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(remove_legacy_retry_schedule),
        migrations.AlterField(
            model_name="agentsession",
            name="agent_type",
            field=models.CharField(
                choices=[("salomao", "Salom\u00e3o")],
                default="salomao",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="conversationinstance",
            name="state",
            field=models.CharField(
                choices=STATE_CHOICES,
                db_index=True,
                default="RECEIVED",
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="conversationstatetransition",
            name="to_state",
            field=models.CharField(
                choices=STATE_CHOICES,
                db_index=True,
                max_length=40,
            ),
        ),
    ]

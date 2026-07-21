"""Add cycle-scoped projection and durable-attempt invariants (Gate C)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add constraints used by cycle-aware reservation and finalization."""

    dependencies = [
        ("support", "0020_conversation_cycles_expand"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="newconversation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("cycle__isnull", False)),
                fields=("cycle",),
                name="uniq_new_conversation_cycle",
            ),
        ),
        migrations.AddConstraint(
            model_name="assignedconversation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("cycle__isnull", False)),
                fields=("cycle",),
                name="uniq_assigned_conversation_cycle",
            ),
        ),
        migrations.AddConstraint(
            model_name="closedconversation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("cycle__isnull", False)),
                fields=("cycle",),
                name="uniq_closed_conversation_cycle",
            ),
        ),
        migrations.AddConstraint(
            model_name="assignmentattempt",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("cycle__isnull", False),
                    (
                        "state__in",
                        ["reserved", "external_applied", "compensating", "retryable", "repair_required"],
                    ),
                ),
                fields=("cycle",),
                name="uniq_live_assignment_cycle",
            ),
        ),
        migrations.AddConstraint(
            model_name="assignmentattempt",
            constraint=models.UniqueConstraint(
                condition=models.Q(("cycle__isnull", False), ("state", "completed")),
                fields=("cycle",),
                name="uniq_completed_assignment_cycle",
            ),
        ),
    ]

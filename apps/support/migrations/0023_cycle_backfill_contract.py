"""Gate E contract: legacy identity metadata and cycle-scoped uniqueness."""

from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def prevent_unsafe_legacy_constraint_restore(apps, schema_editor) -> None:
    """Refuse rollback once valid multi-cycle ticket rows exist."""
    del schema_editor
    for model_name, ticket_field in (
        ("NewConversation", "hubspot_ticket_id"),
        ("AssignedConversation", "hubspot_ticket_id"),
    ):
        model = apps.get_model("support", model_name)
        duplicates = model.objects.values(ticket_field).annotate(n=models.Count("pk")).filter(n__gt=1).exists()
        if duplicates:
            raise IrreversibleError("Gate E rollback would recreate ticket-wide uniqueness over valid multi-cycle rows")
    attempt = apps.get_model("support", "AssignmentAttempt")
    duplicates = attempt.objects.values("ticket_id", "state").annotate(n=models.Count("pk")).filter(n__gt=1).exists()
    if duplicates:
        raise IrreversibleError("Gate E rollback would recreate ticket-wide attempt uniqueness")


class Migration(migrations.Migration):
    """Remove ticket-wide constraints without making nullable rollout FKs mandatory."""

    dependencies = [("support", "0022_closed_conversation_multi_cycle")]

    operations = [
        migrations.AddField(
            model_name="supportconversationcycle",
            name="identity_source",
            field=models.CharField(default="hubspot_stage_entry", max_length=32),
        ),
        migrations.AddField(
            model_name="supportconversationcycle",
            name="identity_evidence_key",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RemoveConstraint(model_name="supportconversationcycle", name="uniq_conv_cycle_natural_key"),
        migrations.AlterField(
            model_name="supportconversationcycle",
            name="entered_stage_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="supportconversationcycle",
            constraint=models.UniqueConstraint(
                condition=models.Q(("entered_stage_at__isnull", False)),
                fields=("source_system", "source_account_id", "hubspot_ticket_id", "entered_stage_at"),
                name="uniq_conv_cycle_natural_key",
            ),
        ),
        migrations.AlterField(
            model_name="newconversation",
            name="hubspot_ticket_id",
            field=models.TextField(db_index=True),
        ),
        migrations.AlterField(
            model_name="assignedconversation",
            name="hubspot_ticket_id",
            field=models.TextField(db_index=True),
        ),
        migrations.RemoveConstraint(model_name="assignmentattempt", name="uniq_live_assignment_attempt_ticket"),
        migrations.RemoveConstraint(model_name="assignmentattempt", name="uniq_completed_assignment_ticket"),
        migrations.RunPython(migrations.RunPython.noop, prevent_unsafe_legacy_constraint_restore),
    ]

"""Allow one closed-conversation projection per support cycle."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Remove the legacy ticket-wide uniqueness from closed history."""

    dependencies = [("support", "0021_cycle_assignment_invariants")]

    operations = [
        migrations.AlterField(
            model_name="closedconversation",
            name="hubspot_ticket_id",
            field=models.TextField(db_index=True),
        ),
    ]

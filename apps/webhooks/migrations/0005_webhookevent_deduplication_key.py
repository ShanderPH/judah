"""Add a provider-aware idempotency key to raw webhook events."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0004_allow_jira_event_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="webhookevent",
            name="deduplication_key",
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
    ]

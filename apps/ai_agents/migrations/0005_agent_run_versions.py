# Generated manually for deterministic workflow alignment.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_agents", "0004_add_waiting_for_customer_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="model_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="policy_version",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="prompt_version",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]

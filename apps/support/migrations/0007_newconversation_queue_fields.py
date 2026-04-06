from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0006_fix_assignment_type_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="newconversation",
            name="queue_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending Assignment"),
                    ("queued", "In Queue (No Agent Available)"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="assignment_attempts",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="last_assignment_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

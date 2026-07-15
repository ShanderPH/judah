from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0013_alter_assignedconversation_pipeline_id_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="newconversation",
            name="queue_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending Assignment"),
                    ("queued", "In Queue (No Agent Available)"),
                    ("failed", "Quarantined After Permanent Failure"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="next_assignment_attempt_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="failure_code",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="failure_message",
            field=models.TextField(blank=True, default=""),
        ),
    ]

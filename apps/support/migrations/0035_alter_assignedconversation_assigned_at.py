from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0034_alter_conversationinstanceattendant_source"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assignedconversation",
            name="assigned_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="conversationreassignment",
            name="reassigned_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]

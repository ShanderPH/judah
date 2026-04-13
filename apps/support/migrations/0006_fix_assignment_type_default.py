from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0005_remove_new_conv_is_pending"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assignmentlog",
            name="assignment_type",
            field=models.TextField(default="automatic"),
        ),
    ]

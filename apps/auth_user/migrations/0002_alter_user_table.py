"""Fix db_table from 'users' to 'auth_users'."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("auth_user", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="user",
            table="auth_users",
        ),
    ]

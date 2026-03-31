"""
Initial migration for auth_user app.
Table auth_users was created in HelpdeskDB via create_judah_new_tables migration.
Run with: python manage.py migrate auth_user --fake-initial
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False)),
                ("username", models.CharField(max_length=150, unique=True)),
                ("first_name", models.CharField(blank=True, default="", max_length=150)),
                ("last_name", models.CharField(blank=True, default="", max_length=150)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("is_staff", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now)),
                ("role", models.CharField(
                    choices=[
                        ("admin", "Admin"),
                        ("manager", "Manager"),
                        ("agent", "Agent"),
                        ("viewer", "Viewer"),
                    ],
                    default="viewer",
                    max_length=20,
                )),
                ("avatar_url", models.URLField(blank=True, null=True)),
                ("hubspot_owner_id", models.CharField(blank=True, max_length=50, null=True)),
                ("is_ai_agent", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("groups", models.ManyToManyField(
                    blank=True,
                    related_name="auth_user_set",
                    related_query_name="user",
                    to="auth.group",
                    verbose_name="groups",
                )),
                ("user_permissions", models.ManyToManyField(
                    blank=True,
                    related_name="auth_user_set",
                    related_query_name="user",
                    to="auth.permission",
                    verbose_name="user permissions",
                )),
            ],
            options={
                "db_table": "auth_users",
                "ordering": ["email"],
                "verbose_name": "User",
                "verbose_name_plural": "Users",
            },
        ),
    ]

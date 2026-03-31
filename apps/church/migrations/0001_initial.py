"""
Initial migration for church app.
Tables church_plans, church_gateways, churches were created
via create_judah_new_tables migration in Supabase.
Run with: python manage.py migrate church --fake-initial
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Plan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=200, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("price", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "church_plans", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Gateway",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=200, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "church_gateways", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Church",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("external_id", models.CharField(db_index=True, max_length=100, unique=True)),
                ("hubspot_company_id", models.CharField(blank=True, max_length=50, null=True)),
                ("name", models.CharField(max_length=500)),
                (
                    "plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="churches",
                        to="church.plan",
                    ),
                ),
                (
                    "gateway",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="churches",
                        to="church.gateway",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("members_count", models.IntegerField(default=0)),
                ("city", models.CharField(blank=True, max_length=200, null=True)),
                ("state", models.CharField(blank=True, max_length=50, null=True)),
                ("country", models.CharField(default="BR", max_length=50)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "churches", "ordering": ["name"]},
        ),
    ]

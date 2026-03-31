"""App configuration for church."""

from django.apps import AppConfig


class ChurchConfig(AppConfig):
    """Configuration for the church application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.church"
    verbose_name = "Church Management"

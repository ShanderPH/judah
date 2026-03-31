"""App configuration for integrations."""

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """Configuration for the integrations application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integrations"
    verbose_name = "External Integrations"

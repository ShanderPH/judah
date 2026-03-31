"""App configuration for webhooks."""

from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    """Configuration for the webhooks application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.webhooks"
    verbose_name = "Webhooks"

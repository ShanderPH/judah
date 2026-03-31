"""App configuration for knowledge."""

from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    """Configuration for the knowledge application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.knowledge"
    verbose_name = "Knowledge Base"

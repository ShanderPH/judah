"""App configuration for ai_agents."""

from django.apps import AppConfig


class AIAgentsConfig(AppConfig):
    """Configuration for the ai_agents application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_agents"
    verbose_name = "AI Agents"

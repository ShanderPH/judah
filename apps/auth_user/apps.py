"""App configuration for auth_user."""

from django.apps import AppConfig


class AuthUserConfig(AppConfig):
    """Configuration for the auth_user application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auth_user"
    verbose_name = "Authentication & Users"

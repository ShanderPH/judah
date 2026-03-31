"""Custom User model for JUDAH."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Usuário customizado do JUDAH com suporte a papéis e integração HubSpot."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        AGENT = "agent", "Agent"
        VIEWER = "viewer", "Viewer"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        db_index=True,
    )
    avatar_url = models.URLField(blank=True)
    hubspot_owner_id = models.CharField(max_length=50, blank=True, db_index=True)
    is_ai_agent = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_full_name()} ({self.role})"

    @property
    def is_admin(self) -> bool:
        """Check if the user has admin role."""
        return self.role == self.Role.ADMIN

    @property
    def is_manager(self) -> bool:
        """Check if the user has manager role."""
        return self.role == self.Role.MANAGER

    @property
    def is_agent(self) -> bool:
        """Check if the user has agent role."""
        return self.role == self.Role.AGENT

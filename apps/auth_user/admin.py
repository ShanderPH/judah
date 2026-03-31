"""Django Admin configuration for auth_user."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.auth_user.models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Extended UserAdmin with JUDAH-specific fields."""

    list_display = ("username", "email", "first_name", "last_name", "role", "is_active", "is_ai_agent")
    list_filter = ("role", "is_active", "is_ai_agent", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name", "hubspot_owner_id")
    ordering = ("-created_at",)

    fieldsets = (  # type: ignore[assignment]
        *UserAdmin.fieldsets,
        (
            "JUDAH",
            {
                "fields": (
                    "role",
                    "avatar_url",
                    "hubspot_owner_id",
                    "is_ai_agent",
                )
            },
        ),
    )

    add_fieldsets = (  # type: ignore[assignment]
        *UserAdmin.add_fieldsets,
        (
            "JUDAH",
            {
                "fields": ("role", "email"),
            },
        ),
    )

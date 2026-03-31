"""Django Admin configuration for church."""

from django.contrib import admin

from apps.church.models import Church, Gateway, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "max_members", "is_active")
    search_fields = ("name", "slug")


@admin.register(Gateway)
class GatewayAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    search_fields = ("name", "slug")


@admin.register(Church)
class ChurchAdmin(admin.ModelAdmin):
    list_display = ("name", "external_id", "city", "state", "plan", "is_active")
    list_filter = ("is_active", "country", "plan")
    search_fields = ("name", "external_id", "email", "hubspot_company_id")
    raw_id_fields = ("plan", "gateway")

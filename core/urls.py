"""Root URL configuration for JUDAH."""

from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI
from ninja_jwt.authentication import JWTAuth

api = NinjaAPI(
    title="JUDAH API",
    version="1.0.0",
    description="Backend unificado da InChurch — plataforma SaaS de gestão de comunidades eclesiásticas.",
    auth=JWTAuth(),
    urls_namespace="judah",
)

api.add_router("/auth/", "apps.auth_user.api.router", tags=["Auth"], auth=None)
api.add_router("/church/", "apps.church.api.router", tags=["Church"])
api.add_router("/knowledge/", "apps.knowledge.api.router", tags=["Knowledge"])
api.add_router("/support/", "apps.support.api.router", tags=["Support"])
api.add_router("/ai/", "apps.ai_agents.api.router", tags=["AI Agents"])
api.add_router("/webhooks/", "apps.webhooks.api.router", tags=["Webhooks"], auth=None)
api.add_router("/analytics/", "apps.analytics.api.router", tags=["Analytics"])
api.add_router("/health/", "apps.health.api.router", tags=["Health"], auth=None)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
]

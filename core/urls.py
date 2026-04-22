"""Root URL configuration for JUDAH."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from ninja import NinjaAPI
from ninja_jwt.authentication import JWTAuth

from common.exceptions import register_exception_handlers

api = NinjaAPI(
    title="JUDAH API",
    version="1.0.0",
    description="Backend unificado da InChurch — plataforma SaaS de gestão de comunidades eclesiásticas.",
    auth=JWTAuth(),
    urls_namespace="judah",
)

register_exception_handlers(api)

api.add_router("/auth/", "apps.auth_user.api.router", tags=["Auth"], auth=None)
api.add_router("/church/", "apps.church.api.router", tags=["Church"])
api.add_router("/knowledge/", "apps.knowledge.api.router", tags=["Knowledge"])
api.add_router("/support/", "apps.support.api.router", tags=["Support"])
api.add_router("/webhooks/", "apps.webhooks.api.router", tags=["Webhooks"], auth=None)
api.add_router("/analytics/", "apps.analytics.api.router", tags=["Analytics"])
api.add_router("/health/", "apps.health.api.router", tags=["Health"], auth=None)

# AI router is gated by a feature flag and is DISABLED by default.
# When off, the supervisor/agents/tasks code is never imported — this keeps
# AI dependencies (Agno, Pinecone, MCP) from breaking unrelated requests,
# and guarantees the legacy auto-assignment / queue system cannot be
# impacted by the dormant AI drop. Flip via AI_ROUTING_ENABLED=true.
if getattr(settings, "AI_ROUTING_ENABLED", False):
    api.add_router("/ai/", "apps.ai_agents.api.router", tags=["AI Agents"])

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
]

# Registra URLs do django-debug-toolbar apenas quando o app está instalado
# (perfil dev). Sem isso, qualquer resposta em DEBUG quebra com NoReverseMatch
# ao renderizar o toolbar — seu middleware é ativado em todas as respostas.
if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

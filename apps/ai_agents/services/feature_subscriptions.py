"""Best-effort lookup of active InRadar modules for an AI-to-N1 handoff."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

LookupStatus = Literal[
    "success",
    "no_modules",
    "missing_church_id",
    "invalid_church_id",
    "not_configured",
    "provider_error",
    "invalid_response",
]


@dataclass(frozen=True)
class ObtainedModule:
    """Safe subset of a feature-subscription record needed by N1."""

    alias: str
    name: str = ""
    price: str = ""
    plan_limit: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "alias": self.alias,
            "name": self.name,
            "price": self.price,
            "plan_limit": self.plan_limit,
        }


@dataclass(frozen=True)
class FeatureSubscriptionLookup:
    """Normalized outcome that can be persisted inside a handoff package."""

    status: LookupStatus
    church_id: str | None
    modules: tuple[ObtainedModule, ...] = ()
    message: str = ""

    def as_handoff_payload(self) -> dict[str, Any]:
        return {
            "church_id": self.church_id,
            "module_lookup_status": self.status,
            "module_lookup_message": self.message,
            "obtained_modules": [module.as_dict() for module in self.modules],
        }


@dataclass(frozen=True)
class ChurchPlanLookup:
    """Plan and availability flags returned for the local church."""

    status: LookupStatus
    church_id: str | None
    plan: str | None = None
    is_active: bool | None = None
    is_blocked: bool | None = None
    message: str = ""

    def as_handoff_payload(self) -> dict[str, Any]:
        return {
            "church_plan_lookup_status": self.status,
            "church_plan_lookup_message": self.message,
            "church_plan": {
                "plan": self.plan,
                "is_active": self.is_active,
                "is_blocked": self.is_blocked,
            }
            if self.status == "success"
            else None,
        }


def normalize_church_id(value: str | int | None) -> str | None:
    """Normalize HubSpot church IDs, accepting the legacy optional ``T`` prefix."""
    if value is None:
        return None
    normalized = str(value).strip()
    match = re.fullmatch(r"[Tt]?(\d+)", normalized)
    if not match:
        return None
    return match.group(1)


def _module_from_record(record: Any) -> ObtainedModule | None:
    if not isinstance(record, dict):
        return None
    feature = record.get("feature")
    plan = record.get("plan")
    if not isinstance(feature, dict):
        return None

    alias = str(feature.get("alias") or "").strip()
    if not alias:
        return None

    name = ""
    price = ""
    plan_limit: str | None = None
    if isinstance(plan, dict):
        name = str(plan.get("name") or "").strip()
        price = str(plan.get("price") or "").strip()
        raw_limit = plan.get("limit")
        if raw_limit is not None and str(raw_limit).strip():
            plan_limit = str(raw_limit).strip()
    return ObtainedModule(alias=alias, name=name, price=price, plan_limit=plan_limit)


def fetch_active_feature_subscriptions(
    church_id: str | int | None,
    *,
    client: httpx.Client | None = None,
) -> FeatureSubscriptionLookup:
    """Fetch active modules without ever making the human handoff depend on InRadar."""
    if church_id is None or not str(church_id).strip():
        return FeatureSubscriptionLookup(
            status="missing_church_id",
            church_id=None,
            message="Código da igreja local não informado no ticket.",
        )

    normalized_church_id = normalize_church_id(church_id)
    if normalized_church_id is None:
        logger.warning(
            "inradar_feature_subscriptions_lookup_skipped",
            church_id=str(church_id),
            error_type="InvalidChurchId",
            message_error="O código da igreja local não possui um formato numérico válido.",
        )
        return FeatureSubscriptionLookup(
            status="invalid_church_id",
            church_id=str(church_id).strip(),
            message="Código da igreja local inválido para consulta.",
        )

    token = str(getattr(settings, "INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN", "") or "").strip()
    if not token:
        logger.warning(
            "inradar_feature_subscriptions_lookup_skipped",
            church_id=normalized_church_id,
            error_type="MissingConfiguration",
            message_error="INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN não está configurado.",
        )
        return FeatureSubscriptionLookup(
            status="not_configured",
            church_id=normalized_church_id,
            message="Consulta de módulos não configurada no ambiente.",
        )

    url = str(settings.INRADAR_FEATURE_SUBSCRIPTIONS_URL)
    timeout = float(settings.INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS)
    owns_client = client is None
    effective_client = client or httpx.Client(timeout=timeout)
    try:
        response = effective_client.post(
            url,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
            },
            json={
                "tertiarygroup": int(normalized_church_id),
                "is_active": True,
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        logger.warning(
            "inradar_feature_subscriptions_lookup_failed",
            church_id=normalized_church_id,
            http_status=status_code,
            error_type=exc.__class__.__name__,
            message_error=(
                "O InRadar rejeitou a consulta de módulos ativos."
                if status_code is not None
                else "A consulta de módulos ativos no InRadar falhou por erro de comunicação."
            ),
            deterministic_handoff_continues=True,
        )
        return FeatureSubscriptionLookup(
            status="provider_error",
            church_id=normalized_church_id,
            message=(
                f"InRadar retornou HTTP {status_code}."
                if status_code is not None
                else "InRadar indisponível no momento."
            ),
        )
    finally:
        if owns_client:
            effective_client.close()

    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, list):
        logger.warning(
            "inradar_feature_subscriptions_invalid_response",
            church_id=normalized_church_id,
            response_type=type(payload).__name__,
            message_error="O InRadar devolveu um formato inesperado para a lista de módulos.",
            deterministic_handoff_continues=True,
        )
        return FeatureSubscriptionLookup(
            status="invalid_response",
            church_id=normalized_church_id,
            message="InRadar devolveu uma resposta inválida.",
        )

    modules_by_alias: dict[str, ObtainedModule] = {}
    for record in payload:
        module = _module_from_record(record)
        if module is not None:
            modules_by_alias.setdefault(module.alias.casefold(), module)
    modules = tuple(modules_by_alias.values())
    status: LookupStatus = "success" if modules else "no_modules"
    logger.info(
        "inradar_feature_subscriptions_lookup_completed",
        church_id=normalized_church_id,
        module_count=len(modules),
        module_aliases=[module.alias for module in modules],
        lookup_status=status,
    )
    return FeatureSubscriptionLookup(
        status=status,
        church_id=normalized_church_id,
        modules=modules,
        message="" if modules else "Nenhum módulo ativo foi retornado.",
    )


def fetch_church_plan(
    church_id: str | int | None,
    *,
    client: httpx.Client | None = None,
) -> ChurchPlanLookup:
    """Fetch the church plan and its active/blocked flags independently of modules."""
    if church_id is None or not str(church_id).strip():
        return ChurchPlanLookup(
            status="missing_church_id",
            church_id=None,
            message="Código da igreja local não informado no ticket.",
        )

    normalized_church_id = normalize_church_id(church_id)
    if normalized_church_id is None:
        logger.warning(
            "inradar_church_plan_lookup_skipped",
            church_id=str(church_id),
            error_type="InvalidChurchId",
            message_error="O código da igreja local não possui um formato numérico válido.",
        )
        return ChurchPlanLookup(
            status="invalid_church_id",
            church_id=str(church_id).strip(),
            message="Código da igreja local inválido para consulta.",
        )

    token = str(getattr(settings, "INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN", "") or "").strip()
    if not token:
        logger.warning(
            "inradar_church_plan_lookup_skipped",
            church_id=normalized_church_id,
            error_type="MissingConfiguration",
            message_error="INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN não está configurado.",
        )
        return ChurchPlanLookup(
            status="not_configured",
            church_id=normalized_church_id,
            message="Consulta do plano da igreja não configurada no ambiente.",
        )

    url = str(settings.INRADAR_TERTIARYGROUP_URL)
    timeout = float(settings.INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS)
    owns_client = client is None
    effective_client = client or httpx.Client(timeout=timeout)
    try:
        response = effective_client.post(
            url,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
            },
            json={"id": int(normalized_church_id)},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        logger.warning(
            "inradar_church_plan_lookup_failed",
            church_id=normalized_church_id,
            http_status=status_code,
            error_type=exc.__class__.__name__,
            message_error=(
                "O InRadar rejeitou a consulta do plano da igreja."
                if status_code is not None
                else "A consulta do plano da igreja no InRadar falhou por erro de comunicação."
            ),
            deterministic_handoff_continues=True,
        )
        return ChurchPlanLookup(
            status="provider_error",
            church_id=normalized_church_id,
            message=(
                f"InRadar retornou HTTP {status_code}."
                if status_code is not None
                else "InRadar indisponível no momento."
            ),
        )
    finally:
        if owns_client:
            effective_client.close()

    try:
        payload = response.json()
    except ValueError:
        payload = None
    if (
        not isinstance(payload, dict)
        or not str(payload.get("plan") or "").strip()
        or not isinstance(payload.get("is_active"), bool)
        or not isinstance(payload.get("is_blocked"), bool)
    ):
        logger.warning(
            "inradar_church_plan_invalid_response",
            church_id=normalized_church_id,
            response_type=type(payload).__name__,
            message_error="O InRadar devolveu um formato inesperado para o plano da igreja.",
            deterministic_handoff_continues=True,
        )
        return ChurchPlanLookup(
            status="invalid_response",
            church_id=normalized_church_id,
            message="InRadar devolveu uma resposta inválida para o plano da igreja.",
        )

    result = ChurchPlanLookup(
        status="success",
        church_id=normalized_church_id,
        plan=str(payload["plan"]).strip(),
        is_active=payload["is_active"],
        is_blocked=payload["is_blocked"],
    )
    logger.info(
        "inradar_church_plan_lookup_completed",
        church_id=normalized_church_id,
        plan=result.plan,
        is_active=result.is_active,
        is_blocked=result.is_blocked,
    )
    return result


__all__ = [
    "ChurchPlanLookup",
    "FeatureSubscriptionLookup",
    "ObtainedModule",
    "fetch_active_feature_subscriptions",
    "fetch_church_plan",
    "normalize_church_id",
]

"""Deterministic HubSpot protocol lookup for customer conversations."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

HUBSPOT_API_BASE = "https://api.hubapi.com"
SUPPORT_N2_PIPELINE_ID = settings.HUBSPOT_N2_PIPELINE_ID
SUPPORT_N2_ENTRY_STAGE_ID = settings.HUBSPOT_N2_ENTRY_STAGE_ID
SUPPORT_N2_CRITICAL_STAGE_ID = settings.HUBSPOT_N2_CRITICAL_STAGE_ID
SUPPORT_N2_HIGH_STAGE_ID = settings.HUBSPOT_N2_HIGH_STAGE_ID
SUPPORT_N2_MEDIUM_STAGE_ID = settings.HUBSPOT_N2_MEDIUM_STAGE_ID
SUPPORT_N2_LOW_STAGE_ID = settings.HUBSPOT_N2_LOW_STAGE_ID
SUPPORT_N2_TRIVIAL_STAGE_ID = settings.HUBSPOT_N2_TRIVIAL_STAGE_ID
SUPPORT_N2_RESOLVED_STAGE_ID = settings.HUBSPOT_N2_RESOLVED_STAGE_ID
SUPPORT_N2_STAGE_STATUS = {
    SUPPORT_N2_ENTRY_STAGE_ID: "Sendo analisado pelo time t\u00e9cnico",
    "1110524173": "Em triagem pelo time t\u00e9cnico",
    SUPPORT_N2_CRITICAL_STAGE_ID: "Em atendimento pelo time t\u00e9cnico",
    SUPPORT_N2_HIGH_STAGE_ID: "Em atendimento pelo time t\u00e9cnico",
    SUPPORT_N2_MEDIUM_STAGE_ID: "Em atendimento pelo time t\u00e9cnico",
    SUPPORT_N2_LOW_STAGE_ID: "Em atendimento pelo time t\u00e9cnico",
    SUPPORT_N2_TRIVIAL_STAGE_ID: "Em atendimento pelo time t\u00e9cnico",
    SUPPORT_N2_RESOLVED_STAGE_ID: "Resolvido",
    "1028692851": "Fechado",
    "960373660": "A\u00e7\u00e3o interna do N1",
    "936942377": "Analisando",
    "936942378": "Solicita\u00e7\u00e3o",
    "937504358": "Bug",
    "1033289605": "Atualiza\u00e7\u00e3o",
    "1208927003": "Em andamento",
    "1245790466": "Aguardando informa\u00e7\u00e3o",
    "1245790467": "Aguardando revis\u00e3o do cliente",
    "1245790468": "Aguardando aceite de termos",
    "1245791369": "Aguardando revis\u00e3o em produ\u00e7\u00e3o",
    "1208927005": "Finalizado",
    "1368995876": "Solicitado",
    "1368995712": "Atualizado",
    "1368986534": "Atualiza\u00e7\u00e3o cancelada",
}
SUPPORT_N2_STAGE_PRIORITY = {
    SUPPORT_N2_CRITICAL_STAGE_ID: "Cr\u00edtica",
    SUPPORT_N2_HIGH_STAGE_ID: "Alta",
    SUPPORT_N2_MEDIUM_STAGE_ID: "M\u00e9dia",
    SUPPORT_N2_LOW_STAGE_ID: "Baixa",
    SUPPORT_N2_TRIVIAL_STAGE_ID: "Trivial",
}
SUPPORT_N2_CLOSED_STAGE_IDS = {
    SUPPORT_N2_RESOLVED_STAGE_ID,
    "1028692851",  # Fechado
    "1208927005",  # Finalizado
    "1368995876",  # Solicitado
    "1368995712",  # Atualizado
    "1368986534",  # Atualiza\u00e7\u00e3o cancelada
}
SUPPORT_N2_OPEN_STAGE_IDS = set(SUPPORT_N2_STAGE_STATUS) - SUPPORT_N2_CLOSED_STAGE_IDS
PRIORITY_LABELS = {
    "LOW": "Baixa",
    "MEDIUM": "M\u00e9dia",
    "HIGH": "Alta",
    "URGENT": "Urgente",
}
DEFAULT_CHURCH_PROPERTY = "codigo_de_igreja_local___ticket"


class ProtocolLookupError(RuntimeError):
    """Customer-safe HubSpot lookup error."""


@dataclass(frozen=True)
class TicketSummary:
    protocol: str
    name: str
    error_area: str | None
    status: str
    priority: str | None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _display_value(value: str | None, *, fallback: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:max_length] if text else fallback


def _priority(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    return PRIORITY_LABELS.get(raw.upper(), raw.title())


class HubSpotProtocolClient:
    """Read-only HubSpot client scoped to support protocol data."""

    def __init__(
        self,
        *,
        access_token: str | None = None,
        church_property: str | None = None,
        base_url: str = HUBSPOT_API_BASE,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.access_token = access_token if access_token is not None else settings.HUBSPOT_ACCESS_TOKEN
        configured_property = getattr(settings, "HUBSPOT_TICKET_CHURCH_PROPERTY", "")
        self.church_property = church_property or configured_property or DEFAULT_CHURCH_PROPERTY
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def get_ticket(self, protocol: str) -> TicketSummary:
        protocol = protocol.strip().lstrip("#")
        if not protocol.isdigit():
            raise ProtocolLookupError("O protocolo informado \u00e9 inv\u00e1lido.")

        response = await self._request(
            "GET",
            f"/crm/v3/objects/tickets/{protocol}",
            params={"properties": ("subject,suporte__area_com_erro,hs_pipeline,hs_pipeline_stage,hs_ticket_priority")},
        )
        if response.status_code == 404:
            raise ProtocolLookupError("N\u00e3o encontrei esse protocolo.")
        self._raise_for_status(response)

        payload = response.json()
        properties = payload.get("properties") or {}
        pipeline_id = str(properties.get("hs_pipeline") or "")
        stage_id = str(properties.get("hs_pipeline_stage") or "")
        if pipeline_id != SUPPORT_N2_PIPELINE_ID:
            raise ProtocolLookupError("Esse protocolo n\u00e3o pertence ao atendimento t\u00e9cnico N2.")
        return self._summary(payload, properties, stage_id)

    async def list_open_tickets_for_church(
        self,
        church_id: str,
        *,
        max_results: int = 1000,
    ) -> list[TicketSummary]:
        church_id = church_id.strip().upper().removeprefix("T")
        if not church_id.isdigit():
            raise ProtocolLookupError("O ID da igreja informado \u00e9 inv\u00e1lido.")

        results: list[dict[str, Any]] = []
        after: str | None = None
        while len(results) < max_results:
            filter_groups = [
                {
                    "filters": [
                        {
                            "propertyName": self.church_property,
                            "operator": "EQ",
                            "value": value,
                        },
                        {
                            "propertyName": "hs_pipeline",
                            "operator": "EQ",
                            "value": SUPPORT_N2_PIPELINE_ID,
                        },
                        {
                            "propertyName": "hs_pipeline_stage",
                            "operator": "IN",
                            "values": sorted(SUPPORT_N2_OPEN_STAGE_IDS),
                        },
                    ]
                }
                for value in (church_id, f"T{church_id}")
            ]
            body: dict[str, Any] = {
                "filterGroups": filter_groups,
                "properties": [
                    self.church_property,
                    "subject",
                    "suporte__area_com_erro",
                    "hs_pipeline",
                    "hs_pipeline_stage",
                    "hs_ticket_priority",
                ],
                "limit": min(100, max_results - len(results)),
            }
            if after:
                body["after"] = after

            response = await self._request("POST", "/crm/v3/objects/tickets/search", json=body)
            self._raise_for_status(response)
            payload = response.json()
            results.extend(payload.get("results") or [])
            after = ((payload.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                break

        tickets: list[TicketSummary] = []
        for item in results[:max_results]:
            properties = item.get("properties") or {}
            stage_id = str(properties.get("hs_pipeline_stage") or "")
            if stage_id not in SUPPORT_N2_OPEN_STAGE_IDS:
                continue
            tickets.append(self._summary(item, properties, stage_id))
        return tickets

    def _summary(
        self,
        payload: dict[str, Any],
        properties: dict[str, Any],
        stage_id: str,
    ) -> TicketSummary:
        return TicketSummary(
            protocol=str(payload.get("id") or ""),
            name=_display_value(
                properties.get("subject"),
                fallback="Ticket sem nome",
                max_length=160,
            ),
            error_area=(
                _display_value(
                    properties.get("suporte__area_com_erro"),
                    fallback="",
                    max_length=100,
                )
                or None
            ),
            status=SUPPORT_N2_STAGE_STATUS.get(stage_id, "Etapa t\u00e9cnica ainda n\u00e3o mapeada"),
            priority=SUPPORT_N2_STAGE_PRIORITY.get(
                stage_id,
                _priority(properties.get("hs_ticket_priority")),
            ),
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.access_token:
            raise ProtocolLookupError("A consulta de protocolos est\u00e1 temporariamente indispon\u00edvel.")
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                return await client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProtocolLookupError("A consulta demorou demais. Tente novamente em instantes.") from exc
        except httpx.HTTPError as exc:
            raise ProtocolLookupError("N\u00e3o foi poss\u00edvel consultar os protocolos agora.") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        logger.warning("hubspot_protocol_lookup_failed", status_code=response.status_code)
        if response.status_code in {401, 403}:
            raise ProtocolLookupError("A consulta de protocolos est\u00e1 temporariamente indispon\u00edvel.")
        if response.status_code == 429:
            raise ProtocolLookupError("Muitas consultas agora. Tente novamente em instantes.")
        raise ProtocolLookupError("N\u00e3o foi poss\u00edvel consultar os protocolos agora.")


class ProtocolConversationHandler:
    """Recognize and answer protocol turns without invoking an AI model."""

    REQUEST_MESSAGE = (
        "Claro. Para consultar somente um ticket, informe o protocolo. "
        "Para listar os protocolos da igreja, informe o ID num\u00e9rico da igreja local, "
        "que geralmente tem 5 d\u00edgitos."
    )
    STATUS_TERMS = (
        "status",
        "andamento",
        "acompanhar",
        "acompanhamento",
        "como esta meu caso",
        "como anda meu caso",
        "meu chamado",
        "meu ticket",
        "meu protocolo",
    )
    PROTOCOL_TERMS = ("protocolo", "ticket", "chamado")

    def __init__(self, client: HubSpotProtocolClient | None = None) -> None:
        self.client = client or HubSpotProtocolClient()

    async def handle(self, context: dict[str, Any]) -> str | None:
        current = self._latest_incoming(context)
        if not current:
            return None

        normalized = _normalize(current).strip()
        history = context.get("conversation_history") or []
        awaiting_identifier = self._awaiting_identifier(history)
        protocol = self._extract_protocol(
            current,
            awaiting_identifier=awaiting_identifier or self._recent_status_intent(history),
        )
        status_intent = self._has_status_intent(normalized)
        mentions_protocol = any(term in normalized for term in self.PROTOCOL_TERMS)
        if protocol and (awaiting_identifier or status_intent or mentions_protocol):
            return await self._ticket_response(protocol)

        church_id = self._extract_church_id(current)
        if church_id:
            return await self._church_response(church_id)

        if protocol and self._recent_status_intent(history):
            return await self._ticket_response(protocol)
        if status_intent or (mentions_protocol and any(term in normalized for term in ("consult", "ver", "saber"))):
            contextual_church_id = self._contextual_church_id(context)
            if contextual_church_id:
                return await self._church_response(contextual_church_id)
            return self.REQUEST_MESSAGE
        return None

    async def _ticket_response(self, protocol: str) -> str:
        try:
            ticket = await self.client.get_ticket(protocol)
        except ProtocolLookupError as exc:
            return str(exc)

        priority = ticket.priority or "N\u00e3o informada"
        lines = [
            "Encontrei o ticket solicitado:",
            "",
            f"- **Protocolo:** #{ticket.protocol}",
            f"- **T\u00edtulo:** {ticket.name}",
            f"- **Status:** {ticket.status}",
            f"- **Prioridade:** {priority}",
        ]
        if ticket.error_area:
            lines.append(f"- **\u00c1rea com erro:** {ticket.error_area}")
        return "\n".join(lines)

    async def _church_response(self, church_id: str) -> str:
        try:
            tickets = await self.client.list_open_tickets_for_church(church_id)
        except ProtocolLookupError as exc:
            return str(exc)
        if not tickets:
            return f"N\u00e3o encontrei protocolos abertos para a igreja {church_id}."

        total = len(tickets)
        noun = "protocolo aberto" if total == 1 else "protocolos abertos"
        lines = [f"Encontrei {total} {noun} para a igreja {church_id}:"]
        for ticket in tickets:
            priority = ticket.priority or "N\u00e3o informada"
            lines.extend(
                [
                    "",
                    f"**Protocolo #{ticket.protocol}**",
                    f"- **T\u00edtulo:** {ticket.name}",
                    f"- **Status:** {ticket.status}",
                    f"- **Prioridade:** {priority}",
                ]
            )
            if ticket.error_area:
                lines.append(f"- **\u00c1rea com erro:** {ticket.error_area}")
        return "\n".join(lines)

    @staticmethod
    def _latest_incoming(context: dict[str, Any]) -> str:
        incoming = [
            str(message.get("text") or "").strip()
            for message in context.get("conversation_history") or []
            if str(message.get("direction") or "").upper() == "INCOMING" and str(message.get("text") or "").strip()
        ]
        return incoming[-1] if incoming else ""

    @classmethod
    def _awaiting_identifier(cls, history: list[dict[str, Any]]) -> bool:
        outgoing = [
            _normalize(str(message.get("text") or ""))
            for message in history
            if str(message.get("direction") or "").upper() == "OUTGOING"
        ]
        return any("informe o protocolo" in message and "id numerico da igreja" in message for message in outgoing[-4:])

    @classmethod
    def _recent_status_intent(cls, history: list[dict[str, Any]]) -> bool:
        incoming = [
            _normalize(str(message.get("text") or ""))
            for message in history[-8:]
            if str(message.get("direction") or "").upper() == "INCOMING"
        ]
        return any(cls._has_status_intent(message) for message in incoming)

    @staticmethod
    def _contextual_church_id(context: dict[str, Any]) -> str | None:
        value = str(context.get("church_id") or "").strip().upper().removeprefix("T")
        return value if value.isdigit() else None

    @classmethod
    def _has_status_intent(cls, normalized: str) -> bool:
        if any(term in normalized for term in cls.STATUS_TERMS):
            return True
        subject = r"(?:caso|chamado|ticket|protocolo|atendimento)"
        state = r"(?:status|andamento|como\s+(?:esta|anda)|acompanhar)"
        return bool(re.search(rf"(?:{subject}).*{state}|(?:{state}).*{subject}", normalized))

    @staticmethod
    def _extract_protocol(message: str, *, awaiting_identifier: bool) -> str | None:
        if awaiting_identifier:
            match = re.fullmatch(r"\s*#?\s*(\d{7,20})\s*", message)
            if match:
                return match.group(1)
        match = re.search(
            r"(?:protocolo|ticket|chamado)\s*(?:n(?:umero|[u\u00fa]mero)?\.?|id|de)?\s*[:#-]?\s*(\d{4,20})\b",
            message,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    @staticmethod
    def _extract_church_id(message: str) -> str | None:
        normalized = _normalize(message).strip()
        prefixed = re.fullmatch(r"t\s*[-#:]?\s*(\d{1,12})", normalized, re.IGNORECASE)
        if prefixed:
            return prefixed.group(1)

        explicit = re.search(
            r"(?:id|codigo)\s+(?:da\s+)?(?:igreja|local)(?:\s+local)?\s*(?:e|eh|:|#|-)?\s*t?\s*(\d{1,12})\b",
            normalized,
            re.IGNORECASE,
        )
        if explicit:
            return explicit.group(1)

        numeric = re.fullmatch(r"\d{1,6}", normalized)
        return numeric.group(0) if numeric else None


async def handle_protocol_lookup_from_hubspot_context(
    context: dict[str, Any],
    *,
    client: HubSpotProtocolClient | None = None,
) -> str | None:
    """Return a customer reply when the latest HubSpot turn is a protocol lookup."""
    return await ProtocolConversationHandler(client=client).handle(context)


__all__ = [
    "HubSpotProtocolClient",
    "ProtocolConversationHandler",
    "ProtocolLookupError",
    "TicketSummary",
    "handle_protocol_lookup_from_hubspot_context",
]

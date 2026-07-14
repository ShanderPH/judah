"""HTTP client for the standalone Salomao v1 service."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog
from django.conf import settings

from apps.integrations.salomao_v1.schemas import SalomaoV1ChatResult
from common.circuit_breaker import CircuitBreaker
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)

_circuit_breaker = CircuitBreaker(name="salomao_v1", failure_threshold=5, recovery_timeout=60)


def is_salomao_v1_configured() -> bool:
    """Return True when Judah should call the standalone Salomao v1 service."""
    return bool(getattr(settings, "SALOMAO_V1_BASE_URL", "").strip())


def is_salomao_v1_provider_error(text: str | None) -> bool:
    """Detect provider/auth errors that Salomao v1 may return as text."""
    if not text:
        return False

    normalized = text.lower()
    markers = (
        "incorrect api key",
        "invalid_api_key",
        "api key provided",
        "insufficient_quota",
        "rate limit",
        "exceeded your current quota",
        "openai.com/account/api-keys",
    )
    return any(marker in normalized for marker in markers)


class SalomaoV1Client:
    """Async client for Salomao v1.

    The external service exposes ``POST /chat`` and keeps its own memory by
    ``session_id``. Judah passes stable session IDs derived from the API user,
    HubSpot ticket, or HubSpot conversation thread.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or getattr(settings, "SALOMAO_V1_BASE_URL", "")).rstrip("/")
        self.timeout_seconds = timeout_seconds or getattr(settings, "SALOMAO_V1_TIMEOUT_SECONDS", 45.0)
        self.transport = transport

        if not self.base_url:
            raise ExternalServiceError("salomao_v1", "SALOMAO_V1_BASE_URL is not configured.")

    async def chat(
        self,
        *,
        message: str,
        session_id: str,
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        audio_base64: str | None = None,
        audio_format: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SalomaoV1ChatResult:
        """Send a chat turn to Salomao v1 and normalize the response."""
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
        }
        if image_base64:
            payload["image_base64"] = image_base64
            payload["image_mime_type"] = image_mime_type or "image/jpeg"
        if audio_base64:
            payload["audio_base64"] = audio_base64
            payload["audio_format"] = audio_format or "wav"

        async def _post_chat() -> httpx.Response:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout_seconds or self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post("/chat", json=payload)
                response.raise_for_status()
                return response

        max_attempts = max(1, int(getattr(settings, "SALOMAO_V1_MAX_ATTEMPTS", 3)))
        response: httpx.Response | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await _circuit_breaker.async_call(_post_chat)
                break
            except httpx.TimeoutException as exc:
                if attempt < max_attempts:
                    logger.warning("salomao_v1_retry", attempt=attempt, reason="timeout")
                    await asyncio.sleep(0.25 * attempt)
                    continue
                raise TimeoutError("Salomao v1 request timed out.") from exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if (status == 429 or status >= 500) and attempt < max_attempts:
                    logger.warning("salomao_v1_retry", attempt=attempt, reason=f"http:{status}")
                    await asyncio.sleep(0.25 * attempt)
                    continue
                logger.warning(
                    "salomao_v1_http_status_error",
                    status=status,
                    body=exc.response.text[:300],
                )
                raise ExternalServiceError(
                    "salomao_v1",
                    f"Salomao v1 returned HTTP {status}.",
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < max_attempts:
                    logger.warning("salomao_v1_retry", attempt=attempt, reason=type(exc).__name__)
                    await asyncio.sleep(0.25 * attempt)
                    continue
                raise ExternalServiceError("salomao_v1", "Could not reach Salomao v1.") from exc

        if response is None:  # pragma: no cover - defensive guard
            raise ExternalServiceError("salomao_v1", "Salomao v1 did not return a response.")

        try:
            result = SalomaoV1ChatResult.model_validate(response.json())
        except ValueError as exc:
            raise ExternalServiceError("salomao_v1", "Salomao v1 returned invalid JSON.") from exc

        if not result.success:
            raise ExternalServiceError("salomao_v1", result.error or "Salomao v1 chat failed.")

        if is_salomao_v1_provider_error(result.response):
            raise ExternalServiceError("salomao_v1", "Salomao v1 provider credential or quota error.")

        return result


async def send_chat_to_salomao_v1(
    *,
    message: str,
    session_id: str,
    image_base64: str | None = None,
    image_mime_type: str | None = None,
    audio_base64: str | None = None,
    audio_format: str | None = None,
) -> SalomaoV1ChatResult:
    """Convenience wrapper used by API endpoints and Celery pipelines."""
    client = SalomaoV1Client()
    return await client.chat(
        message=message,
        session_id=session_id,
        image_base64=image_base64,
        image_mime_type=image_mime_type,
        audio_base64=audio_base64,
        audio_format=audio_format,
    )


__all__ = [
    "SalomaoV1Client",
    "is_salomao_v1_configured",
    "is_salomao_v1_provider_error",
    "send_chat_to_salomao_v1",
]

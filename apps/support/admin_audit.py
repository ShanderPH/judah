"""Transactional audit and idempotency boundary for administrative actions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.support.models import AdministrativeActionAudit
from common.exceptions import ConflictError, ValidationError

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _json_safe(value: Any) -> Any:
    """Return a JSON-compatible value without retaining model or request objects."""
    return json.loads(json.dumps(value, default=str, separators=(",", ":")))


def _request_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(_json_safe(dict(payload)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_key(request: Any) -> str | None:
    headers = getattr(request, "headers", {})
    raw = headers.get("Idempotency-Key") or headers.get("X-Idempotency-Key")
    if raw is None:
        meta = getattr(request, "META", {})
        raw = meta.get("HTTP_IDEMPOTENCY_KEY") or meta.get("HTTP_X_IDEMPOTENCY_KEY")
    if raw is None or not str(raw).strip():
        return None
    key = str(raw).strip()
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise ValidationError("Idempotency-Key must be 1-128 characters using letters, digits, '.', '_', ':' or '-'.")
    return key


def _correlation_id(request: Any) -> str:
    meta = getattr(request, "META", {})
    value = meta.get("X_REQUEST_ID") or meta.get("HTTP_X_REQUEST_ID")
    return str(value or uuid.uuid4())[:64]


def _actor(request: Any) -> tuple[str, str]:
    user = getattr(request, "auth", None)
    return str(getattr(user, "pk", ""))[:64], str(getattr(user, "role", ""))[:32]


def _replay(
    audit: AdministrativeActionAudit,
    *,
    fingerprint: str,
) -> tuple[int, Any]:
    if audit.request_fingerprint != fingerprint:
        raise ConflictError("Idempotency-Key was already used with a different request.")
    if audit.status != AdministrativeActionAudit.Status.SUCCEEDED or audit.http_status is None:
        raise ConflictError("The previous request with this Idempotency-Key did not complete successfully.")
    return audit.http_status, audit.response_payload


def _record_failure(
    *,
    request: Any,
    action: str,
    target_type: str,
    target_id: str,
    reason: str,
    idempotency_key: str | None,
    fingerprint: str,
    exc: Exception,
) -> None:
    actor_id, actor_role = _actor(request)
    defaults = {
        "actor_id": actor_id,
        "actor_role": actor_role,
        "target_type": target_type,
        "target_id": target_id[:255],
        "reason": reason[:255],
        "correlation_id": _correlation_id(request),
        "request_fingerprint": fingerprint,
        "status": AdministrativeActionAudit.Status.FAILED,
        "http_status": getattr(exc, "status_code", 500),
        "error_code": type(exc).__name__[:128],
        "completed_at": timezone.now(),
    }
    if idempotency_key is None:
        AdministrativeActionAudit.objects.create(action=action, idempotency_key=None, **defaults)
        return
    AdministrativeActionAudit.objects.get_or_create(
        action=action,
        idempotency_key=idempotency_key,
        defaults=defaults,
    )


def execute_audited_action[T](
    request: Any,
    *,
    action: str,
    target_type: str,
    target_id: str = "",
    reason: str,
    fingerprint_payload: Mapping[str, Any],
    operation: Callable[[], tuple[int, T]],
) -> tuple[int, T]:
    """Execute a write only after reserving its append-only audit record.

    A repeated idempotency key replays the stored response. Reusing the key
    with a different fingerprint is rejected before the operation runs.
    """
    key = _idempotency_key(request)
    fingerprint = _request_fingerprint(fingerprint_payload)
    actor_id, actor_role = _actor(request)
    normalized_reason = reason.strip()[:255] or action

    try:
        with transaction.atomic():
            defaults = {
                "actor_id": actor_id,
                "actor_role": actor_role,
                "target_type": target_type,
                "target_id": target_id[:255],
                "reason": normalized_reason,
                "correlation_id": _correlation_id(request),
                "request_fingerprint": fingerprint,
            }
            if key is None:
                audit = AdministrativeActionAudit.objects.create(
                    action=action,
                    idempotency_key=None,
                    **defaults,
                )
            else:
                audit, created = AdministrativeActionAudit.objects.get_or_create(
                    action=action,
                    idempotency_key=key,
                    defaults=defaults,
                )
                if not created:
                    status, payload = _replay(audit, fingerprint=fingerprint)
                    return status, payload

            http_status, payload = operation()
            audit.status = AdministrativeActionAudit.Status.SUCCEEDED
            audit.http_status = http_status
            audit.response_payload = _json_safe(payload)
            audit.completed_at = timezone.now()
            audit.save(
                update_fields=("status", "http_status", "response_payload", "completed_at"),
            )
            return http_status, payload
    except Exception as exc:
        if isinstance(exc, ConflictError):
            raise
        try:
            _record_failure(
                request=request,
                action=action,
                target_type=target_type,
                target_id=target_id,
                reason=normalized_reason,
                idempotency_key=key,
                fingerprint=fingerprint,
                exc=exc,
            )
        except Exception:
            # The administrative write was rolled back. Preserve the original
            # exception and never attempt the operation without an audit row.
            raise exc from None
        raise

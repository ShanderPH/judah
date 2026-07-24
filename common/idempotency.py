"""Canonical idempotency helpers shared by inbound event ledgers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_HUBSPOT_TRANSPORT_FIELDS = frozenset({"attemptNumber", "attempt_number"})


def canonical_event_key(*, source: str, event_type: str, payload: Mapping[str, Any]) -> str:
    """Fingerprint the complete provider event instead of trusting its local ID.

    HubSpot's ``eventId`` is not globally unique. Including the source, event
    type, and canonical payload keeps exact redeliveries idempotent while
    allowing distinct events that happen to reuse the same provider ID.
    """
    normalized_source = str(source).strip().lower()
    stable_payload = dict(payload)
    if normalized_source == "hubspot":
        stable_payload = {key: value for key, value in stable_payload.items() if key not in _HUBSPOT_TRANSPORT_FIELDS}
    canonical = {
        "source": normalized_source,
        "event_type": str(event_type).strip(),
        "payload": stable_payload,
    }
    serialized = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"event:v2:{digest}"

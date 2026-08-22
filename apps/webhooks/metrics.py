"""PII-free structured metric events for the inbound integration."""

from __future__ import annotations

from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)

MetricKind = Literal["counter", "gauge", "histogram"]


def emit_metric(name: str, value: int | float = 1, *, kind: MetricKind = "counter", **dimensions: Any) -> None:
    """Emit one aggregator-friendly metric event without message content."""
    logger.info(
        "integration_metric",
        metric_name=name,
        metric_kind=kind,
        metric_value=value,
        **dimensions,
    )


__all__ = ["emit_metric"]

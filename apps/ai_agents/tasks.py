"""Celery tasks for the AI agents pipeline.

The HubSpot ticket-change webhook used to dispatch the supervisor pipeline
via ``asyncio.create_task``. That tied long-running LLM work to the request
event loop, so a worker restart mid-run lost the task silently and retries
from HubSpot would double-fire the pipeline.

Moving the work to Celery gives us durable scheduling, worker-level
concurrency control, and — combined with a Redis ``SETNX`` lock — protects
against duplicate execution when HubSpot retries the same webhook.
"""

from __future__ import annotations

import asyncio

import redis
import structlog
from django.conf import settings

from celery import shared_task

logger = structlog.get_logger(__name__)


# Ten minutes is comfortably longer than the typical supervisor pipeline
# latency and short enough that a crashed worker's lock will expire before
# HubSpot's retry window runs out.
_IDEMPOTENCY_TTL_SECONDS = 600
_LOCK_KEY_PREFIX = "salomao:supervisor:ticket"


def _redis_client() -> redis.Redis:
    redis_url: str = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(redis_url)


@shared_task(name="ai_agents.run_supervisor_pipeline_task")
def run_supervisor_pipeline_task(ticket_id: str, is_off_hours: bool = False) -> None:
    """Run the Salomão supervisor pipeline for a HubSpot ticket.

    Acquires a short-lived Redis lock keyed on ``ticket_id`` so that duplicate
    HubSpot webhook retries do not trigger overlapping pipeline runs. The lock
    is best-effort — if Redis is unreachable, we fall through and execute
    anyway rather than drop the event.
    """
    ticket_id = str(ticket_id)
    lock_key = f"{_LOCK_KEY_PREFIX}:{ticket_id}"

    client: redis.Redis | None
    try:
        client = _redis_client()
        acquired = bool(client.set(lock_key, "1", nx=True, ex=_IDEMPOTENCY_TTL_SECONDS))
    except redis.RedisError as exc:
        logger.warning(
            "supervisor_pipeline_lock_unavailable",
            ticket_id=ticket_id,
            error=str(exc),
        )
        client = None
        acquired = True

    if not acquired:
        logger.info(
            "supervisor_pipeline_duplicate_skipped",
            ticket_id=ticket_id,
            lock_key=lock_key,
        )
        return

    from apps.ai_agents.api.webhooks import _run_supervisor_pipeline

    try:
        asyncio.run(_run_supervisor_pipeline(ticket_id, is_off_hours=is_off_hours))
    finally:
        if client is not None:
            try:
                client.delete(lock_key)
            except redis.RedisError as exc:
                logger.warning(
                    "supervisor_pipeline_lock_release_failed",
                    ticket_id=ticket_id,
                    error=str(exc),
                )


__all__ = ["run_supervisor_pipeline_task"]

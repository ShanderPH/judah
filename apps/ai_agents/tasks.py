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
_STAGE_TRIGGER_DEDUPE_TTL_SECONDS = 60
_LOCK_KEY_PREFIX = "salomao:supervisor:ticket"
_THREAD_LOCK_KEY_PREFIX = "salomao:supervisor:thread"
_PENDING_KEY_PREFIX = "salomao:supervisor:pending"
_STAGE_TRIGGER_KEY_PREFIX = "salomao:supervisor:stage-trigger"


def _redis_client() -> redis.Redis:
    redis_url: str = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(redis_url)


@shared_task(name="ai_agents.run_supervisor_pipeline_task")
def run_supervisor_pipeline_task(
    ticket_id: str,
    is_off_hours: bool = False,
    enforce_ai_pipeline: bool = False,
    queue_if_busy: bool = False,
) -> None:
    """Run the Salomão supervisor pipeline for a HubSpot ticket.

    Acquires a short-lived Redis lock keyed on ``ticket_id`` so that duplicate
    HubSpot webhook retries do not trigger overlapping pipeline runs. The lock
    is best-effort — if Redis is unreachable, we fall through and execute
    anyway rather than drop the event.
    """
    ticket_id = str(ticket_id)
    lock_key = f"{_LOCK_KEY_PREFIX}:{ticket_id}"
    pending_key = f"{_PENDING_KEY_PREFIX}:{ticket_id}"
    stage_trigger_key = f"{_STAGE_TRIGGER_KEY_PREFIX}:{ticket_id}"

    client: redis.Redis | None
    try:
        client = _redis_client()
        if not queue_if_busy:
            first_stage_trigger = bool(
                client.set(stage_trigger_key, "1", nx=True, ex=_STAGE_TRIGGER_DEDUPE_TTL_SECONDS)
            )
            if not first_stage_trigger:
                logger.info("supervisor_pipeline_stage_trigger_deduplicated", ticket_id=ticket_id)
                return
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
        if client is not None and queue_if_busy:
            try:
                client.set(pending_key, "1", ex=_IDEMPOTENCY_TTL_SECONDS)
            except redis.RedisError as exc:
                logger.warning("supervisor_pipeline_pending_mark_failed", ticket_id=ticket_id, error=str(exc))
        logger.info(
            "supervisor_pipeline_busy",
            ticket_id=ticket_id,
            lock_key=lock_key,
            followup_queued=queue_if_busy,
        )
        return

    from apps.ai_agents.api.webhooks import _run_supervisor_pipeline

    try:
        asyncio.run(
            _run_supervisor_pipeline(
                ticket_id,
                is_off_hours=is_off_hours,
                enforce_ai_pipeline=enforce_ai_pipeline,
            )
        )
    finally:
        run_followup = False
        if client is not None:
            try:
                client.delete(lock_key)
                run_followup = bool(client.delete(pending_key))
            except redis.RedisError as exc:
                logger.warning(
                    "supervisor_pipeline_lock_release_failed",
                    ticket_id=ticket_id,
                    error=str(exc),
                )
        if run_followup:
            run_supervisor_pipeline_task.delay(ticket_id, is_off_hours, enforce_ai_pipeline, False)
            logger.info("supervisor_pipeline_followup_dispatched", ticket_id=ticket_id)


@shared_task(name="ai_agents.run_salomao_v1_thread_pipeline_task")
def run_salomao_v1_thread_pipeline_task(thread_id: str) -> None:
    """Run the Supervisor for a HubSpot conversation thread.

    This is used by ``conversation.newMessage`` webhooks. The task re-fetches
    the thread before responding and only answers if the latest usable message
    is incoming from the visitor. The task name is kept for deployed queue
    compatibility; Salomao v1 is now an internal Supervisor member.
    """
    thread_id = str(thread_id)
    lock_key = f"{_THREAD_LOCK_KEY_PREFIX}:{thread_id}"

    client: redis.Redis | None
    try:
        client = _redis_client()
        acquired = bool(client.set(lock_key, "1", nx=True, ex=_IDEMPOTENCY_TTL_SECONDS))
    except redis.RedisError as exc:
        logger.warning(
            "supervisor_thread_lock_unavailable",
            thread_id=thread_id,
            error=str(exc),
        )
        client = None
        acquired = True

    if not acquired:
        logger.info(
            "supervisor_thread_duplicate_skipped",
            thread_id=thread_id,
            lock_key=lock_key,
        )
        return

    from apps.ai_agents.api.webhooks import _run_salomao_v1_thread_pipeline

    try:
        asyncio.run(_run_salomao_v1_thread_pipeline(thread_id))
    finally:
        if client is not None:
            try:
                client.delete(lock_key)
            except redis.RedisError as exc:
                logger.warning(
                    "supervisor_thread_lock_release_failed",
                    thread_id=thread_id,
                    error=str(exc),
                )


@shared_task(name="ai_agents.run_lifecycle_watchdog_task")
def run_lifecycle_watchdog_task() -> dict[str, int]:
    """Detect stuck workflows and dispatch retries whose backoff has expired."""
    from django.utils import timezone

    from apps.ai_agents.models import ConversationInstance
    from apps.ai_agents.services.lifecycle import InvalidStateTransitionError, LifecycleEngine
    from apps.ai_agents.services.watchdog import run_lifecycle_watchdog

    watchdog = run_lifecycle_watchdog(limit=100, max_failures=3)
    due_instances = list(
        ConversationInstance.objects.filter(
            state=ConversationInstance.State.FAILED_RETRYABLE,
            next_retry_at__lte=timezone.now(),
        ).order_by("next_retry_at")[:100]
    )
    engine = LifecycleEngine()
    dispatched = 0

    for instance in due_instances:
        try:
            engine.transition(
                instance,
                ConversationInstance.State.CONTEXT_HYDRATING,
                reason="Lifecycle retry backoff expired.",
                actor_type="watchdog",
            )
        except InvalidStateTransitionError as exc:
            logger.warning(
                "lifecycle_retry_transition_skipped",
                conversation_instance_id=str(instance.pk),
                error=str(exc),
            )
            continue

        instance.next_retry_at = None
        instance.current_error = ""
        instance.save(update_fields=["next_retry_at", "current_error", "updated_at"])
        if instance.hubspot_ticket_id:
            run_supervisor_pipeline_task.delay(str(instance.hubspot_ticket_id), False, True, True)
            dispatched += 1
        elif instance.hubspot_thread_id:
            run_salomao_v1_thread_pipeline_task.delay(str(instance.hubspot_thread_id))
            dispatched += 1
        else:
            logger.error("lifecycle_retry_missing_target", conversation_instance_id=str(instance.pk))

    return {
        "scanned": watchdog.scanned,
        "marked_retryable": watchdog.marked_retryable,
        "marked_terminal": watchdog.marked_terminal,
        "retries_dispatched": dispatched,
    }


__all__ = [
    "run_lifecycle_watchdog_task",
    "run_salomao_v1_thread_pipeline_task",
    "run_supervisor_pipeline_task",
]

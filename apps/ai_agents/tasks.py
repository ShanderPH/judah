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
_THREAD_LOCK_KEY_PREFIX = "salomao:supervisor:thread"


def _redis_client() -> redis.Redis:
    redis_url: str = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(redis_url)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="ai_agents.run_supervisor_pipeline_task",
)
def run_supervisor_pipeline_task(self, ticket_id: str, is_off_hours: bool = False) -> None:
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
    except Exception as exc:
        countdown = min(30 * (2**self.request.retries), 300)
        logger.warning(
            "supervisor_pipeline_retry",
            ticket_id=ticket_id,
            retry=self.request.retries,
            countdown=countdown,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown) from exc
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


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="ai_agents.run_salomao_v1_thread_pipeline_task",
)
def run_salomao_v1_thread_pipeline_task(self, thread_id: str) -> None:
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
    except Exception as exc:
        countdown = min(30 * (2**self.request.retries), 300)
        logger.warning(
            "supervisor_thread_retry",
            thread_id=thread_id,
            retry=self.request.retries,
            countdown=countdown,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown) from exc
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


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="ai_agents.request_human_handoff_task",
)
def request_human_handoff_task(
    self,
    *,
    thread_id: str | None = None,
    ticket_id: str | None = None,
    reason: str,
) -> None:
    """Hydrate minimal context and enqueue a deterministic human handoff."""
    from apps.ai_agents.services.execution import ensure_conversation_instance, request_human_handoff
    from apps.ai_agents.services.hubspot import (
        build_conversation_context_from_hubspot_context,
        hydrate_thread_context,
        hydrate_ticket_context,
    )

    try:
        if thread_id:
            context = asyncio.run(hydrate_thread_context(str(thread_id)))
            session_id = (
                f"hubspot-ticket-{context.get('ticket_id')}"
                if context.get("ticket_id")
                else f"hubspot-thread-{thread_id}"
            )
        elif ticket_id:
            context = asyncio.run(hydrate_ticket_context(str(ticket_id)))
            session_id = f"hubspot-ticket-{ticket_id}"
        else:
            raise ValueError("thread_id or ticket_id is required for human handoff.")

        instance = ensure_conversation_instance(
            context=context,
            ticket_id=ticket_id or context.get("ticket_id") or None,
            session_id=session_id,
        )
        conversation_context = build_conversation_context_from_hubspot_context(
            context,
            session_id=session_id,
        )
        request_human_handoff(
            instance=instance,
            reason=reason,
            conversation_context=conversation_context,
            triage_decision=None,
            ai_summary=reason,
        )
    except Exception as exc:
        countdown = min(30 * (2**self.request.retries), 300)
        logger.warning(
            "human_handoff_retry",
            thread_id=thread_id,
            ticket_id=ticket_id,
            retry=self.request.retries,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown) from exc


@shared_task(name="ai_agents.run_lifecycle_watchdog_task")
def run_lifecycle_watchdog_task() -> dict[str, int]:
    """Detect stuck lifecycle instances on a periodic schedule."""
    from apps.ai_agents.services.watchdog import run_lifecycle_watchdog

    result = run_lifecycle_watchdog()
    return {
        "scanned": result.scanned,
        "marked_retryable": result.marked_retryable,
        "marked_terminal": result.marked_terminal,
    }


@shared_task(name="ai_agents.retry_failed_lifecycle_instances_task")
def retry_failed_lifecycle_instances_task(limit: int = 100) -> dict[str, int]:
    """Re-dispatch due retryable instances or hand off exhausted failures."""
    from django.utils import timezone

    from apps.ai_agents.contracts import ConversationContext
    from apps.ai_agents.models import ConversationInstance
    from apps.ai_agents.services.execution import request_human_handoff
    from apps.ai_agents.services.lifecycle import LifecycleEngine

    due = list(
        ConversationInstance.objects.filter(
            state=ConversationInstance.State.FAILED_RETRYABLE,
            next_retry_at__lte=timezone.now(),
        ).order_by("next_retry_at")[:limit]
    )
    redispatched = 0
    handed_off = 0
    terminal = 0

    for instance in due:
        if instance.failure_count >= 3:
            if instance.hubspot_ticket_id:
                context = ConversationContext(
                    channel="hubspot",
                    session_id=instance.ai_session_id or f"hubspot-ticket-{instance.hubspot_ticket_id}",
                    ticket_id=instance.hubspot_ticket_id,
                    thread_id=instance.hubspot_thread_id,
                    contact_id=instance.hubspot_contact_id,
                    pipeline_id=instance.pipeline_id,
                    pipeline_stage=instance.pipeline_stage_id,
                    can_send_reply=False,
                )
                request_human_handoff(
                    instance=instance,
                    reason=f"Retry budget exhausted: {instance.current_error}",
                    conversation_context=context,
                    triage_decision=None,
                    ai_summary="Falha técnica persistente; atendimento transferido com segurança.",
                )
                handed_off += 1
            else:
                LifecycleEngine().transition(
                    instance,
                    ConversationInstance.State.FAILED_TERMINAL,
                    reason="Retry budget exhausted and no ticket is available for human handoff.",
                )
                terminal += 1
            continue

        instance.next_retry_at = None
        instance.save(update_fields=["next_retry_at", "updated_at"])
        if instance.hubspot_thread_id:
            run_salomao_v1_thread_pipeline_task.delay(instance.hubspot_thread_id)
            redispatched += 1
        elif instance.hubspot_ticket_id:
            run_supervisor_pipeline_task.delay(instance.hubspot_ticket_id, False)
            redispatched += 1
        else:
            LifecycleEngine().transition(
                instance,
                ConversationInstance.State.FAILED_TERMINAL,
                reason="Retryable instance has no routable HubSpot identifier.",
            )
            terminal += 1

    return {
        "scanned": len(due),
        "redispatched": redispatched,
        "handed_off": handed_off,
        "terminal": terminal,
    }


__all__ = [
    "request_human_handoff_task",
    "retry_failed_lifecycle_instances_task",
    "run_lifecycle_watchdog_task",
    "run_salomao_v1_thread_pipeline_task",
    "run_supervisor_pipeline_task",
]

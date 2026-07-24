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
import time
import uuid
from functools import lru_cache
from typing import Any

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
_THREAD_PENDING_KEY_PREFIX = "salomao:supervisor:thread-pending"
_STAGE_TRIGGER_KEY_PREFIX = "salomao:supervisor:stage-trigger"
_MESSAGE_BATCH_TOKEN_KEY_PREFIX = "salomao:message-batch:token"
_MESSAGE_BATCH_STARTED_KEY_PREFIX = "salomao:message-batch:started"
_MESSAGE_BATCH_TTL_SECONDS = 300
_CLAIM_MESSAGE_BATCH_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    redis.call('del', KEYS[1], KEYS[2])
    return 1
end
return 0
"""


@lru_cache(maxsize=4)
def _shared_lock_client(redis_url: str, max_connections: int) -> redis.Redis:
    """Reuse a bounded lock pool instead of creating one per Celery task."""
    pool = redis.BlockingConnectionPool.from_url(
        redis_url,
        max_connections=max_connections,
        timeout=2,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    return redis.Redis(connection_pool=pool)


def _redis_client() -> redis.Redis:
    redis_url: str = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    max_connections = int(getattr(settings, "REDIS_LOCK_MAX_CONNECTIONS", 2))
    return _shared_lock_client(redis_url, max_connections)


def _message_batch_windows() -> tuple[float, float]:
    """Return bounded quiet and maximum wait windows for customer bursts."""
    quiet_seconds = max(
        0.5,
        min(float(getattr(settings, "SALOMAO_MESSAGE_QUIET_SECONDS", 4.0)), 30.0),
    )
    max_wait_seconds = max(
        quiet_seconds,
        min(float(getattr(settings, "SALOMAO_MESSAGE_MAX_WAIT_SECONDS", 12.0)), 60.0),
    )
    return quiet_seconds, max_wait_seconds


def _decode_redis_value(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _schedule_customer_message_batch(
    *,
    scope: str,
    identifier: str,
    task: Any,  # Celery's decorated task proxy has no useful static protocol.
    args: tuple[object, ...],
) -> str | None:
    """Schedule only the newest task after a short customer-message pause."""
    quiet_seconds, max_wait_seconds = _message_batch_windows()
    now = time.time()
    token = uuid.uuid4().hex
    token_key = f"{_MESSAGE_BATCH_TOKEN_KEY_PREFIX}:{scope}:{identifier}"
    started_key = f"{_MESSAGE_BATCH_STARTED_KEY_PREFIX}:{scope}:{identifier}"

    coordinated = False
    countdown = quiet_seconds
    try:
        client = _redis_client()
        client.set(started_key, f"{now:.6f}", nx=True, ex=_MESSAGE_BATCH_TTL_SECONDS)
        started_raw = _decode_redis_value(client.get(started_key))
        try:
            started_at = float(started_raw)
        except TypeError, ValueError:
            started_at = now
        client.set(token_key, token, ex=_MESSAGE_BATCH_TTL_SECONDS)
        countdown = max(0.0, min(quiet_seconds, started_at + max_wait_seconds - now))
        coordinated = True
        logger.info(
            "salomao_customer_message_batched",
            scope=scope,
            identifier=identifier,
            countdown_seconds=round(countdown, 3),
            max_wait_seconds=max_wait_seconds,
        )
    except redis.RedisError as exc:
        # HubSpot remains the durable message store. If coordination is down,
        # delayed tasks and the existing per-conversation locks still prevent
        # loss and most duplicate processing.
        logger.warning(
            "salomao_customer_message_batch_degraded",
            scope=scope,
            identifier=identifier,
            countdown_seconds=quiet_seconds,
            error=str(exc),
        )
    if coordinated:
        task.apply_async(
            args=args,
            kwargs={"message_batch_token": token},
            countdown=countdown,
        )
    else:
        task.apply_async(args=args, countdown=countdown)
    return token if coordinated else None


def _claim_customer_message_batch(
    *,
    scope: str,
    identifier: str,
    token: str | None,
) -> tuple[bool, redis.Redis | None]:
    """Atomically allow only the newest delayed task to process a burst."""
    if not token:
        return True, None
    token_key = f"{_MESSAGE_BATCH_TOKEN_KEY_PREFIX}:{scope}:{identifier}"
    started_key = f"{_MESSAGE_BATCH_STARTED_KEY_PREFIX}:{scope}:{identifier}"
    try:
        client = _redis_client()
        claimed = bool(
            client.eval(
                _CLAIM_MESSAGE_BATCH_SCRIPT,
                2,
                token_key,
                started_key,
                token,
            )
        )
    except redis.RedisError as exc:
        logger.warning(
            "salomao_customer_message_batch_claim_degraded",
            scope=scope,
            identifier=identifier,
            error=str(exc),
        )
        return True, None
    if not claimed:
        logger.info(
            "salomao_customer_message_batch_superseded",
            scope=scope,
            identifier=identifier,
        )
    return claimed, client


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="ai_agents.run_supervisor_pipeline_task",
)
def run_supervisor_pipeline_task(
    self,
    ticket_id: str,
    is_off_hours: bool = False,
    enforce_ai_pipeline: bool = False,
    queue_if_busy: bool = False,
    message_batch_token: str | None = None,
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

    claimed, batch_client = _claim_customer_message_batch(
        scope="ticket",
        identifier=ticket_id,
        token=message_batch_token,
    )
    if not claimed:
        return

    client: redis.Redis | None
    try:
        client = batch_client or _redis_client()
        if not queue_if_busy:
            first_stage_trigger = bool(
                client.set(
                    stage_trigger_key,
                    "1",
                    nx=True,
                    ex=_STAGE_TRIGGER_DEDUPE_TTL_SECONDS,
                )
            )
            if not first_stage_trigger:
                logger.info(
                    "supervisor_pipeline_stage_trigger_deduplicated",
                    ticket_id=ticket_id,
                )
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
                logger.warning(
                    "supervisor_pipeline_pending_mark_failed",
                    ticket_id=ticket_id,
                    error=str(exc),
                )
        logger.info(
            "supervisor_pipeline_busy",
            ticket_id=ticket_id,
            lock_key=lock_key,
            followup_queued=queue_if_busy,
        )
        return

    from apps.ai_agents.api.webhooks import _run_supervisor_pipeline

    succeeded = False
    try:
        asyncio.run(
            _run_supervisor_pipeline(
                ticket_id,
                is_off_hours=is_off_hours,
                enforce_ai_pipeline=enforce_ai_pipeline,
            )
        )
        succeeded = True
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
        run_followup = False
        if client is not None:
            try:
                client.delete(lock_key)
                if succeeded:
                    run_followup = bool(client.delete(pending_key))
            except redis.RedisError as exc:
                logger.warning(
                    "supervisor_pipeline_lock_release_failed",
                    ticket_id=ticket_id,
                    error=str(exc),
                )
        if run_followup:
            run_supervisor_pipeline_task.delay(
                ticket_id,
                is_off_hours,
                enforce_ai_pipeline,
                True,
            )
            logger.info(
                "supervisor_pipeline_followup_dispatched",
                ticket_id=ticket_id,
            )


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="ai_agents.run_salomao_v1_thread_pipeline_task",
)
def run_salomao_v1_thread_pipeline_task(
    self,
    thread_id: str,
    message_batch_token: str | None = None,
) -> None:
    """Run the Supervisor for a HubSpot conversation thread.

    This is used by ``conversation.newMessage`` webhooks. The task re-fetches
    the thread before responding and only answers if the latest usable message
    is incoming from the visitor. The task name is kept for deployed queue
    compatibility; Salomao v1 is now an internal Supervisor member.
    """
    thread_id = str(thread_id)
    lock_key = f"{_THREAD_LOCK_KEY_PREFIX}:{thread_id}"
    pending_key = f"{_THREAD_PENDING_KEY_PREFIX}:{thread_id}"

    claimed, batch_client = _claim_customer_message_batch(
        scope="thread",
        identifier=thread_id,
        token=message_batch_token,
    )
    if not claimed:
        return

    client: redis.Redis | None
    try:
        client = batch_client or _redis_client()
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
        if client is not None:
            try:
                client.set(pending_key, "1", ex=_IDEMPOTENCY_TTL_SECONDS)
            except redis.RedisError as exc:
                logger.warning(
                    "supervisor_thread_pending_mark_failed",
                    thread_id=thread_id,
                    error=str(exc),
                )
        logger.info(
            "supervisor_thread_busy",
            thread_id=thread_id,
            lock_key=lock_key,
            followup_queued=True,
        )
        return

    from apps.ai_agents.api.webhooks import _run_salomao_v1_thread_pipeline
    from apps.ai_agents.services.hubspot import hydrate_thread_context

    succeeded = False
    ticket_id = ""
    ticket_lock_key = ""
    ticket_pending_key = ""
    ticket_lock_acquired = False
    try:
        context = asyncio.run(hydrate_thread_context(thread_id))
        ticket_id = str(context.get("ticket_id") or "")
        if client is not None and ticket_id:
            ticket_lock_key = f"{_LOCK_KEY_PREFIX}:{ticket_id}"
            ticket_pending_key = f"{_PENDING_KEY_PREFIX}:{ticket_id}"
            ticket_lock_acquired = bool(
                client.set(
                    ticket_lock_key,
                    "1",
                    nx=True,
                    ex=_IDEMPOTENCY_TTL_SECONDS,
                )
            )
            if not ticket_lock_acquired:
                # Keep the retry attached to this exact conversation. A
                # ticket-level follow-up could hydrate a different thread.
                client.set(pending_key, "1", ex=_IDEMPOTENCY_TTL_SECONDS)
                logger.info(
                    "supervisor_thread_ticket_busy",
                    thread_id=thread_id,
                    ticket_id=ticket_id,
                    followup_queued="thread",
                )
                succeeded = True
                return

        asyncio.run(_run_salomao_v1_thread_pipeline(thread_id, context=context))
        succeeded = True
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
        run_thread_followup = False
        run_ticket_followup = False
        if client is not None:
            try:
                if ticket_lock_acquired:
                    client.delete(ticket_lock_key)
                client.delete(lock_key)
                if succeeded:
                    run_thread_followup = bool(client.delete(pending_key))
                    if ticket_lock_acquired:
                        run_ticket_followup = bool(client.delete(ticket_pending_key))
            except redis.RedisError as exc:
                logger.warning(
                    "supervisor_thread_lock_release_failed",
                    thread_id=thread_id,
                    error=str(exc),
                )
        if run_thread_followup:
            run_salomao_v1_thread_pipeline_task.delay(thread_id)
            logger.info(
                "supervisor_thread_followup_dispatched",
                thread_id=thread_id,
            )
        elif run_ticket_followup:
            run_supervisor_pipeline_task.delay(ticket_id, False, True, True)
            logger.info(
                "supervisor_thread_ticket_followup_dispatched",
                thread_id=thread_id,
                ticket_id=ticket_id,
            )


def schedule_supervisor_customer_turn(
    ticket_id: str,
    *,
    is_off_hours: bool,
    enforce_ai_pipeline: bool = True,
) -> str | None:
    """Debounce and schedule a ticket-backed customer message turn."""
    ticket_id = str(ticket_id)
    return _schedule_customer_message_batch(
        scope="ticket",
        identifier=ticket_id,
        task=run_supervisor_pipeline_task,
        args=(ticket_id, is_off_hours, enforce_ai_pipeline, True),
    )


def schedule_salomao_thread_customer_turn(thread_id: str) -> str | None:
    """Debounce and schedule a conversation-thread customer message turn."""
    thread_id = str(thread_id)
    return _schedule_customer_message_batch(
        scope="thread",
        identifier=thread_id,
        task=run_salomao_v1_thread_pipeline_task,
        args=(thread_id,),
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
            session_id = f"hubspot-thread-{thread_id}"
        elif ticket_id:
            context = asyncio.run(hydrate_ticket_context(str(ticket_id)))
            hydrated_thread_ids = context.get("thread_ids") or []
            session_id = (
                f"hubspot-thread-{hydrated_thread_ids[0]}" if hydrated_thread_ids else f"hubspot-ticket-{ticket_id}"
            )
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
    "schedule_salomao_thread_customer_turn",
    "schedule_supervisor_customer_turn",
]

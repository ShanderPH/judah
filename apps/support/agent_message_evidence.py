"""Attribute a support cycle to agents with proven participation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from apps.support.models import Agent, AssignedConversation, AssignmentLog, ClosedConversation, ConversationReassignment
from apps.webhooks.models import WebhookEvent


def attributed_agent_cycles(cycle_ids: set[UUID] | None = None) -> set[tuple[UUID, int]]:
    """Count a prior owner only when an outbound message proves their participation."""
    if cycle_ids is not None and not cycle_ids:
        return set()

    owner_by_cycle: dict[UUID, int] = {}
    assignment_started: dict[tuple[UUID, int], datetime] = {}
    projected_cycles: set[UUID] = set()
    for model in (AssignedConversation, ClosedConversation):
        rows = model.objects.filter(cycle__isnull=False)
        if cycle_ids is not None:
            rows = rows.filter(cycle_id__in=cycle_ids)
        for cycle_id, owner_id in rows.values_list("cycle_id", "hubspot_owner_id"):
            projected_cycles.add(cycle_id)
            if owner_id is not None:
                owner_by_cycle[cycle_id] = owner_id
            else:
                owner_by_cycle.pop(cycle_id, None)

    logs = AssignmentLog.objects.filter(
        cycle__isnull=False,
        hubspot_owner_id__isnull=False,
    )
    if cycle_ids is not None:
        logs = logs.filter(cycle_id__in=cycle_ids)
    for cycle_id, owner_id, assigned_at in logs.order_by("assigned_at", "pk").values_list(
        "cycle_id", "hubspot_owner_id", "assigned_at"
    ):
        if owner_id is None or assigned_at is None:
            continue
        if cycle_id not in projected_cycles:
            owner_by_cycle[cycle_id] = owner_id
        key = (cycle_id, owner_id)
        if key not in assignment_started or assigned_at < assignment_started[key]:
            assignment_started[key] = assigned_at

    transfers = (
        ConversationReassignment.objects.filter(
            cycle__isnull=False,
            from_hubspot_owner_id__isnull=False,
            to_hubspot_owner_id__isnull=False,
            reassigned_at__isnull=False,
        )
        .exclude(reassignment_source__startswith="forced_reassignment:reserved")
        .select_related("cycle")
    )
    if cycle_ids is not None:
        transfers = transfers.filter(cycle_id__in=cycle_ids)
    transfers = list(transfers.order_by("reassigned_at", "pk"))
    owner_ids = {transfer.from_hubspot_owner_id for transfer in transfers}
    users_by_owner: dict[int, set[str]] = defaultdict(set)
    for owner_id, user_id in Agent.objects.filter(hubspot_owner_id__in=owner_ids).values_list(
        "hubspot_owner_id", "hubspot_user_id"
    ):
        if user_id:
            users_by_owner[owner_id].add(user_id)

    attributed = {(cycle_id, owner_id) for cycle_id, owner_id in owner_by_cycle.items()}
    transfer_starts: dict[tuple[UUID, int], datetime] = {}
    message_windows: dict[tuple[str, str, str], list[tuple[datetime, datetime, UUID, int]]] = defaultdict(list)
    for transfer in transfers:
        from_owner = transfer.from_hubspot_owner_id
        to_owner = transfer.to_hubspot_owner_id
        transfer_at = transfer.reassigned_at
        cycle_id = transfer.cycle_id
        if cycle_id is None or from_owner is None or to_owner is None or transfer_at is None:
            continue
        key = (cycle_id, from_owner)
        starts = [value for value in (assignment_started.get(key), transfer_starts.get(key)) if value is not None]
        transfer_starts[(cycle_id, to_owner)] = transfer_at
        user_ids = users_by_owner[from_owner]
        if len(user_ids) != 1:
            continue
        if not starts:
            continue
        started_at = max(starts)
        if started_at >= transfer_at:
            continue
        start = max(started_at, transfer.cycle.opened_at)
        if transfer.cycle.closed_at is not None and start >= transfer.cycle.closed_at:
            continue
        ended_at = min(transfer_at, transfer.cycle.closed_at or transfer_at)
        if start >= ended_at:
            continue
        actor_id = f"A-{next(iter(user_ids))}"
        message_windows[(transfer.cycle.source_account_id, transfer.hubspot_ticket_id, actor_id)].append(
            (start, ended_at, cycle_id, from_owner)
        )

    windows = list(message_windows.items())
    for offset in range(0, len(windows), 100):
        batch = dict(windows[offset : offset + 100])
        starts = [start for intervals in batch.values() for start, _, _, _ in intervals]
        ends = [end for intervals in batch.values() for _, end, _, _ in intervals]
        messages = WebhookEvent.objects.filter(
            source="hubspot",
            portal_id__in={key[0] for key in batch},
            hubspot_ticket_id__in={key[1] for key in batch},
            ignored_reason="outgoing_message",
            occurred_at__gte=min(starts),
            occurred_at__lt=max(ends),
            payload___agent_message_evidence__actor_id__in={key[2] for key in batch},
        ).values_list("portal_id", "hubspot_ticket_id", "occurred_at", "payload___agent_message_evidence__actor_id")
        for portal_id, ticket_id, occurred_at, actor_id in messages.iterator(chunk_size=1000):
            for start, end, cycle_id, owner_id in batch.get((portal_id, ticket_id, actor_id), ()):
                if start <= occurred_at < end:
                    attributed.add((cycle_id, owner_id))
    return attributed

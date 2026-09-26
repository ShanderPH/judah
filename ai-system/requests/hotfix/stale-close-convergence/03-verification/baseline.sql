BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';

SELECT json_build_object(
    'assigned_total', (SELECT count(*) FROM assigned_conversations),
    'assigned_with_closed_occupancy', (
        SELECT count(*)
        FROM assigned_conversations AS assigned
        JOIN support_ticket_occupancies AS occupancy
          ON occupancy.hubspot_ticket_id = assigned.hubspot_ticket_id
        WHERE occupancy.state = 'closed'
    ),
    'assigned_cycles', (
        SELECT count(*) FROM support_conversation_cycles WHERE state = 'assigned'
    ),
    'close_occurrences', (
        SELECT count(*)
        FROM conversation_events
        WHERE event_type = 'ticket_closed'
          AND payload->>'propertyName' = 'hs_v2_date_entered_939275052'
    ),
    'closed_projections', (SELECT count(*) FROM closed_conversations),
    'lifecycle_closes', (
        SELECT count(*) FROM conversation_state_transitions WHERE to_state = 'CLOSED'
    )
);

WITH close_occurrences AS (
    SELECT event.created_at,
           instance.hubspot_ticket_id,
           CASE
               WHEN event.payload->>'propertyValue' ~ '^[0-9]{13}$'
               THEN to_timestamp((event.payload->>'propertyValue')::bigint / 1000.0)
           END AS closed_at
    FROM conversation_events AS event
    JOIN conversation_instances AS instance ON instance.id = event.instance_id
    WHERE event.source = 'hubspot'
      AND event.event_type = 'ticket_closed'
      AND event.payload->>'propertyName' = 'hs_v2_date_entered_939275052'
), resolved AS (
    SELECT occurrence.created_at,
           occurrence.closed_at,
           cycle.id AS cycle_id,
           cycle.state AS cycle_state,
           cycle.entered_stage_at AS cycle_entered_at,
           assigned.id AS assigned_id,
           closed.id AS closed_id
    FROM close_occurrences AS occurrence
    LEFT JOIN LATERAL (
        SELECT candidate.id, candidate.state, candidate.entered_stage_at
        FROM support_conversation_cycles AS candidate
        WHERE candidate.hubspot_ticket_id = occurrence.hubspot_ticket_id
          AND candidate.entered_stage_at <= occurrence.closed_at
        ORDER BY candidate.entered_stage_at DESC
        LIMIT 1
    ) AS cycle ON true
    LEFT JOIN assigned_conversations AS assigned ON assigned.cycle_id = cycle.id
    LEFT JOIN closed_conversations AS closed ON closed.cycle_id = cycle.id
)
SELECT json_build_object(
    'valid_close_occurrences', count(*) FILTER (WHERE closed_at IS NOT NULL),
    'no_cycle', count(*) FILTER (WHERE closed_at IS NOT NULL AND cycle_id IS NULL),
    'cycle_assigned_without_closed', count(*) FILTER (
        WHERE cycle_state = 'assigned' AND closed_id IS NULL
    ),
    'assigned_projection_without_closed', count(*) FILTER (
        WHERE assigned_id IS NOT NULL AND closed_id IS NULL
    ),
    'assigned_cycles_without_closed', count(DISTINCT cycle_id) FILTER (
        WHERE assigned_id IS NOT NULL AND closed_id IS NULL
    ),
    'cycle_closed_without_projection', count(*) FILTER (
        WHERE cycle_state = 'closed' AND closed_id IS NULL
    ),
    'new_24h_assigned_without_closed', count(*) FILTER (
        WHERE cycle_entered_at >= now() - interval '24 hours'
          AND assigned_id IS NOT NULL AND closed_id IS NULL
    ),
    'new_24h_assigned_cycles_without_closed', count(DISTINCT cycle_id) FILTER (
        WHERE cycle_entered_at >= now() - interval '24 hours'
          AND assigned_id IS NOT NULL AND closed_id IS NULL
    )
)
FROM resolved;

ROLLBACK;

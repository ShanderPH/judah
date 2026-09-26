-- Run with psql -v deploy_at='2026-09-26T00:00:00Z' -v source_account_id='<HUBSPOT_PORTAL_ID>' -f live-close-cohorts.sql.
-- Replace deploy_at with the actual UTC deployment instant of the new SHA.
-- Replace source_account_id with the authoritative HubSpot portal ID.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';

WITH close_occurrences AS (
    SELECT :'source_account_id'::text AS source_account_id,
           instance.hubspot_ticket_id,
           CASE
               WHEN event.payload->>'propertyValue' ~ '^[0-9]{13}$'
               THEN to_timestamp((event.payload->>'propertyValue')::bigint / 1000.0)
           END AS effective_at
    FROM conversation_events AS event
    JOIN conversation_instances AS instance ON instance.id = event.instance_id
    WHERE event.source = 'hubspot'
      AND event.event_type = 'ticket_closed'
      AND event.payload->>'propertyName' = 'hs_v2_date_entered_939275052'
), resolved AS (
    SELECT occurrence.effective_at,
           cycle.id AS cycle_id,
           cycle.created_at AS cycle_created_at
    FROM close_occurrences AS occurrence
    JOIN LATERAL (
        SELECT candidate.id, candidate.created_at, candidate.source_account_id,
               candidate.hubspot_ticket_id
        FROM support_conversation_cycles AS candidate
        WHERE candidate.source_account_id = occurrence.source_account_id
          AND candidate.hubspot_ticket_id = occurrence.hubspot_ticket_id
          AND candidate.entered_stage_at <= occurrence.effective_at
        ORDER BY candidate.entered_stage_at DESC
        LIMIT 1
    ) AS cycle ON true
    JOIN support_ticket_occupancies AS occupancy
      ON occupancy.source_account_id = cycle.source_account_id
     AND occupancy.hubspot_ticket_id = cycle.hubspot_ticket_id
     AND occupancy.state = 'closed'
    JOIN support_conversation_cycles AS current_cycle ON current_cycle.id = cycle.id
    WHERE current_cycle.state IN ('queued', 'assigned')
      AND NOT EXISTS (SELECT 1 FROM closed_conversations AS closed WHERE closed.cycle_id = cycle.id)
)
SELECT CASE
           WHEN cycle_created_at >= :'deploy_at'::timestamptz
            AND effective_at >= :'deploy_at'::timestamptz THEN 'new_code'
           ELSE 'historical_backlog'
       END AS cohort,
       count(DISTINCT cycle_id) AS divergent_cycles
FROM resolved
GROUP BY cohort
ORDER BY cohort;

ROLLBACK;

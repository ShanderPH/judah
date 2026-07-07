# Modelos por App

## Resumo

Lista dos principais modelos Django do JUDAH, com campos, restrições e finalidade. Modelos legados são indicados quando aplicável.

## Contexto

Modelos definem a estrutura do PostgreSQL. Cada app possui seu próprio `models.py`. Alguns modelos mapeiam tabelas existentes do HelpdeskDB.

---

## `apps.auth_user`

### `User` → `auth_users`

Extende `AbstractUser`.

| Campo | Tipo | Notas |
|-------|------|-------|
| `role` | CharField(choices) | admin, manager, agent, viewer |
| `avatar_url` | URLField | opcional |
| `hubspot_owner_id` | CharField | indexado |
| `is_ai_agent` | BooleanField | default False |
| `created_at` / `updated_at` | DateTimeField | auto |

---

## `apps.church`

### `Plan` → `plans`

| Campo | Tipo | Notas |
|-------|------|-------|
| `name` / `slug` | CharField | únicos |
| `max_members` | PositiveIntegerField | 0 = ilimitado? |
| `is_active` | BooleanField | |

### `Gateway` → `gateways`

| Campo | Tipo | Notas |
|-------|------|-------|
| `name` / `slug` | CharField | slug único |
| `is_active` | BooleanField | |

### `Church` → `churches`

| Campo | Tipo | Notas |
|-------|------|-------|
| `external_id` | CharField | único, indexado |
| `name`, `email`, `phone`, `city`, `state`, `country` | — | dados cadastrais |
| `plan` / `gateway` | FK | nullable |
| `hubspot_company_id` | CharField | indexado |
| `is_active` | BooleanField | indexado |

---

## `apps.knowledge`

### `Category` → `kb_categories`

| Campo | Tipo | Notas |
|-------|------|-------|
| `hubspot_id` | CharField | único, indexado |
| `name`, `description`, `full_path`, `icon_name`, `color` | — | |
| `position` / `article_count` | IntegerField | |

### `Article` → `kb_articles`

| Campo | Tipo | Notas |
|-------|------|-------|
| `hubspot_id` | CharField | único, indexado |
| `title`, `slug`, `path` | — | slug indexado |
| `body_html`, `body_plain`, `summary` | TextField | |
| `state` | CharField | default `PUBLISHED`, indexado |
| `category_hubspot_id` | CharField | indexado |
| `tags`, `tag_ids` | JSONField | |
| `synced_at` | DateTimeField | |

### `ArticleChunk` → `kb_article_chunks`

| Campo | Tipo | Notas |
|-------|------|-------|
| `article` | FK | nullable |
| `article_hubspot_id` | CharField | indexado |
| `pinecone_id` | CharField | único, indexado |
| `chunk_index` | IntegerField | |
| `chunk_text` | TextField | |
| `unique_together` | — | `(article, chunk_index)` |

### `KBSyncLog` → `kb_sync_logs`

| Campo | Tipo | Notas |
|-------|------|-------|
| `sync_type` | CharField | |
| `total_articles`, `articles_created`, etc. | IntegerField | |
| `status` | CharField | |
| `metadata` | JSONField | |

---

## `apps.support`

### `Agent` → `agents`

| Campo | Tipo | Notas |
|-------|------|-------|
| `name` / `agent_email` | TextField | email único |
| `hubspot_owner_id` | BigIntegerField | |
| `status_enum` | CharField | online, away, offline, busy |
| `current_simultaneous_chats` | BigIntegerField | default 0 |
| `max_simultaneous_chats` | IntegerField | default 5 |
| `auto_assign_enabled` | BooleanField | default True |
| `is_active` | BooleanField | nullable |
| `working_hours`, `skills` | JSONField | |
| `online_time_seconds_today` / `away_time_seconds_today` | IntegerField | |
| `Indexes` | — | `(status_enum, auto_assign_enabled)`, `(hubspot_owner_id)` |

### `Ticket` → `tickets`

| Campo | Tipo | Notas |
|-------|------|-------|
| `ticket_id` | TextField | único, indexado |
| `customer_name`, `ticket_church`, `category`, `priority`, `status` | TextField | textos livres |
| `affected_device`, `scope_of_impact`, `affected_module`, `affected_functionality` | TextField | |
| `created_at` | DateTimeField | indexado |
| `closed_at` | DateTimeField | nullable |
| `Indexes` | — | `(status, priority)`, `(ticket_church, status)` |

> **Nota:** `apps/analytics/services.py` referencia `Ticket.Status.RESOLVED`, `Ticket.resolved_at` e `Ticket.sla_breached`, mas esses campos **não existem** no modelo atual. O service `compute_daily_report` está quebrado até que o modelo ou o service seja ajustado.

### `NewConversation` → `new_conversations`

| Campo | Tipo | Notas |
|-------|------|-------|
| `hubspot_ticket_id` | TextField | único, indexado |
| `pipeline_id` | TextField | default `636459134` |
| `contact_name`, `contact_email`, `priority`, `subject` | TextField | |
| `entered_queue_at` | DateTimeField | indexado |
| `queue_status` | CharField | pending / queued |
| `assignment_attempts` | IntegerField | default 0 |

### `AssignedConversation` → `assigned_conversations`

| Campo | Tipo | Notas |
|-------|------|-------|
| `hubspot_ticket_id` | TextField | único, indexado |
| `agent` | FK | nullable |
| `hubspot_owner_id` | BigIntegerField | indexado |
| `agent_name` | TextField | |
| `entered_queue_at`, `assigned_at`, `closed_at` | DateTimeField | |
| `queue_wait_seconds`, `total_handle_time_minutes` | DecimalField | |
| `assignment_count` | IntegerField | default 1 |
| `Indexes` | — | `(hubspot_owner_id, assigned_at)`, `(assigned_at)` |

### `ClosedConversation` → `closed_conversations`

| Campo | Tipo | Notas |
|-------|------|-------|
| `hubspot_ticket_id` | TextField | único, indexado |
| `agent` | FK | nullable |
| `hubspot_owner_id` | BigIntegerField | indexado |
| `closed_at` | DateTimeField | indexado |
| `queue_wait_seconds`, `total_handle_time_minutes`, `resolution_time_minutes` | DecimalField | |
| `closure_source` | CharField | default `agent` |
| `Indexes` | — | `(closed_at)`, `(hubspot_owner_id, closed_at)` |

### `AssignmentLog` → `assignment_logs`

| Campo | Tipo | Notas |
|-------|------|-------|
| `ticket_id` | TextField | indexado |
| `agent` | FK | nullable |
| `hubspot_owner_id` | BigIntegerField | nullable |
| `assignment_type` | TextField | default `automatic` |
| `assigned_at` | DateTimeField | auto |
| `Indexes` | — | `(assignment_type, -assigned_at)` |

### `ConversationReassignment` → `conversation_reassignments`

| Campo | Tipo | Notas |
|-------|------|-------|
| `hubspot_ticket_id` | TextField | indexado |
| `from_agent` / `to_agent` | FK | nullable |
| `from_hubspot_owner_id` / `to_hubspot_owner_id` | BigIntegerField | |
| `reassigned_at` | DateTimeField | indexado |
| `time_with_previous_agent_seconds` | DecimalField | |
| `Indexes` | — | `(hubspot_ticket_id, reassigned_at)`, `(from_hubspot_owner_id, reassigned_at)`, `(to_hubspot_owner_id, reassigned_at)` |

### `QueuePerformanceMetrics` → `queue_performance_metrics`

| Campo | Tipo | Notas |
|-------|------|-------|
| `metric_date` | DateField | único, indexado |
| `total_entered_queue`, `total_assigned`, `total_closed` | IntegerField | |
| `avg/min/max/p50/p95_queue_wait_seconds` | DecimalField | |
| `avg_handle_time_minutes` | DecimalField | |
| `assignments_by_agent` | JSONField | |

### `AgentMetrics` → `agent_metrics`

| Campo | Tipo | Notas |
|-------|------|-------|
| `agent_id` | BigIntegerField | indexado |
| `period_start` / `period_end` | DateField | nullable |
| `total_chats`, `chats_closed` | IntegerField | |
| `first_response_time_avg_min`, `resolution_rate`, `customer_satisfaction_avg` | DecimalField | |

### `AgentDailyTimeLog` → `agent_daily_time_logs`

| Campo | Tipo | Notas |
|-------|------|-------|
| `agent` | FK | |
| `log_date` | DateField | indexado |
| `online_time_seconds`, `away_time_seconds` | IntegerField | |
| `status_transitions` | IntegerField | |
| `Constraint` | — | `(agent, log_date)` unique |

### `BusinessHoursConfig` → `business_hours_config`

| Campo | Tipo | Notas |
|-------|------|-------|
| `name` | CharField | |
| `is_active` | BooleanField | |
| `monday_start/end` ... `sunday_start/end` | IntegerField | |
| `timezone_name` | CharField | |

### `SpecialSchedule` → `special_schedules`

| Campo | Tipo | Notas |
|-------|------|-------|
| `date` | DateField | único, indexado |
| `schedule_type` | CharField | closed / custom |
| `start_hour` / `end_hour` | IntegerField | nullable |
| `reason` | TextField | |

---

## `apps.ai_agents`

### `AgentSession` → `agent_sessions`

| Campo | Tipo | Notas |
|-------|------|-------|
| `session_id` | CharField | único, indexado |
| `agent_type` | CharField | salomao / heimdall |
| `user_identifier`, `channel`, `hubspot_contact_id`, `church_external_id` | CharField | |
| `is_active` | BooleanField | |
| `ended_at` | DateTimeField | nullable |

### `AgentMemory` → `agent_memories`

| Campo | Tipo | Notas |
|-------|------|-------|
| `session` | FK | |
| `key` / `value` | CharField / TextField | |
| `unique_together` | — | `(session, key)` |

### `AgentTrace` → `agent_traces`

| Campo | Tipo | Notas |
|-------|------|-------|
| `session` | FK | |
| `role` | CharField | user / assistant / tool |
| `content` | TextField | |
| `tool_name`, `tool_input`, `tool_output` | — | |
| `tokens_used`, `latency_ms` | IntegerField | |

### `TokenTrackingLog` → `token_tracking_logs`

| Campo | Tipo | Notas |
|-------|------|-------|
| `session_id` | CharField | indexado |
| `ticket_id` | CharField | nullable, indexado |
| `model_name` | CharField | |
| `prompt_tokens`, `completion_tokens` | IntegerField | |
| `total_cost_usd` | DecimalField | 10,6 |

---

## `apps.webhooks`

### `WebhookEvent` → `webhook_events`

| Campo | Tipo | Notas |
|-------|------|-------|
| `event_type` | TextField | indexado |
| `event_id` / `object_id` | TextField | indexado |
| `property_name` / `property_value` | TextField | nullable |
| `payload` | JSONField | |
| `processed` / `processed_at` | BooleanField / DateTimeField | |
| `retry_count` / `error_message` | IntegerField / TextField | |
| `Indexes` | — | `(event_type, processed)` |

### `DeadLetterQueue` → `webhook_dead_letters`

| Campo | Tipo | Notas |
|-------|------|-------|
| `event` | OneToOne FK | |
| `failure_reason` | TextField | |

---

## `apps.analytics`

### `Metric` → `analytics_metrics`

| Campo | Tipo | Notas |
|-------|------|-------|
| `metric_type` | CharField | choices |
| `date` | DateField | indexado |
| `value` | FloatField | |
| `dimensions` | JSONField | |
| `Indexes` | — | `(metric_type, date)` |

### `DailyReport` → `analytics_daily_reports`

| Campo | Tipo | Notas |
|-------|------|-------|
| `date` | DateField | único, indexado |
| `total_tickets_opened`, `total_tickets_resolved`, `total_tickets_escalated` | IntegerField | |
| `avg_resolution_hours`, `avg_first_response_hours`, `sla_compliance_rate` | FloatField | |
| `ai_handled_count`, `ai_deflection_rate` | — | |
| `top_queues` | JSONField | |

### `AgentPerformance` → `analytics_agent_performance`

| Campo | Tipo | Notas |
|-------|------|-------|
| `agent` | FK | settings.AUTH_USER_MODEL |
| `date` | DateField | indexado |
| `tickets_handled`, `tickets_resolved`, `sla_breached_count` | IntegerField | |
| `avg_resolution_hours`, `avg_first_response_hours` | FloatField | |
| `unique_together` | — | `(agent, date)` |

## Arquivos relacionados

- [`database/relationships.md`](./relationships.md)
- [`database/migrations.md`](./migrations.md)

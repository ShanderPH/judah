# Visão Geral do Banco de Dados

## Resumo

O JUDAH usa PostgreSQL 16 como banco de dados principal, hospedado no Supabase. O Django ORM gerencia modelos, migrations e consultas. Redis é usado para cache, broker Celery e sessão de agentes, mas não para persistência transacional.

## Contexto

O schema do banco reflete a migração de sistemas legados: várias tabelas mapeiam nomes antigos (`webhook_events`, `kb_articles`, `agents`, `tickets`) e novas tabelas foram adicionadas para funcionalidades do JUDAH (`new_conversations`, `assigned_conversations`, `closed_conversations`, etc.).

## Tecnologia

| Aspecto | Escolha |
|---------|---------|
| SGBD | PostgreSQL 16 |
| Host | Supabase (dev/prod) |
| Driver | `psycopg[binary]` 3.x |
| Pool | `dj_database_url` com `conn_max_age` |
| Migrations | Django migrations |
| Cache/Broker | Redis 7 |

## Configuração de conexão

```python
# core/settings/base.py
DATABASES = {
    "default": dj_database_url.parse(
        config("DATABASE_URL"),
        conn_max_age=60,
    )
}
```

Em produção, se a porta for `6543` (Supavisor transaction mode), `CONN_MAX_AGE=0`.

## Tabelas por app

| App | Tabelas principais |
|-----|-------------------|
| `auth_user` | `auth_users` |
| `church` | `plans`, `gateways`, `churches` |
| `knowledge` | `kb_categories`, `kb_articles`, `kb_article_chunks`, `kb_sync_logs` |
| `support` | `agents`, `tickets`, `agent_status_history`, `agent_metrics`, `new_conversations`, `assigned_conversations`, `closed_conversations`, `queue_performance_metrics`, `assignment_logs`, `conversation_reassignments`, `business_hours_config`, `special_schedules`, `agent_daily_time_logs` |
| `ai_agents` | `agent_sessions`, `agent_memories`, `agent_traces`, `token_tracking_logs` |
| `webhooks` | `webhook_events`, `webhook_dead_letters` |
| `analytics` | `analytics_metrics`, `analytics_daily_reports`, `analytics_agent_performance` |
| Django/contrib | `auth_*`, `django_*`, `token_blacklist_*`, `django_celery_beat_*` |

## Estratégias de persistência

- **Django ORM** para todas as entidades transacionais.
- **Pinecone** para embeddings e busca vetorial.
- **Redis** para cache, sessões de IA e broker Celery.
- **S3/storage** não está configurado no backend; static files são servidos pelo whitenoise.

## Arquivos relacionados

- [`database/models.md`](./models.md)
- [`database/relationships.md`](./relationships.md)
- [`database/migrations.md`](./migrations.md)
- [`core/settings/base.py`](../../core/settings/base.py)
- [`core/settings/production.py`](../../core/settings/production.py)

## Pontos de atenção

- Algumas tabelas legadas têm campos nulos/permissivos para compatibilidade.
- `support.Ticket` usa textos livres para `status` e `priority`.
- `analytics.DailyReport.compute_daily_report` referencia `Ticket.sla_breached`, mas o campo não existe.

## Recomendações

- Criar diagrama ER automatizado (ex: `django-extensions graph_models`).
- Revisar constraints e índices conforme carga de dados aumenta.
- Documentar política de retenção de `AgentTrace` e `TokenTrackingLog`.

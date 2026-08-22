# Mapa rápido

- `core/urls.py`: routers públicos ativos.
- `core/settings/`: Django, Celery e configurações operacionais.
- `apps/webhooks/`: ingestão durável HubSpot/Jira.
- `apps/ai_agents/services/lifecycle.py`: ledger e máquina de estados.
- `apps/support/`: filas, agentes, Matchmaker, calendário e métricas.
- `apps/integrations/hubspot/`: cliente HubSpot compartilhado.
- `apps/knowledge/` e `apps/ai_agents/agents/rag.py`: knowledge/RAG independente.
- `apps/integrations/salomao_v1/`: adaptador Salomão independente.

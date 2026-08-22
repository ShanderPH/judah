# Contexto para agentes de desenvolvimento

JUDAH é responsável pelo lifecycle operacional do Help Desk, filas, Matchmaker,
agentes, calendário, métricas, Celery, HubSpot e persistência compartilhada.

Não reintroduza identificação ou triagem no backend. O n8n assume coleta,
confirmação de identidade e triagem. O JUDAH apenas entrega mensagens inbound
pelo contrato durável em `../architecture/n8n-inbound-adapter.md`.

Preserve `apps/support`, o ledger de `apps/ai_agents`, HubSpot compartilhado,
RAG, knowledge e Salomão independente. Execute testes somente com isolamento
local seguro.

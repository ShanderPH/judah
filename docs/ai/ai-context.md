# Contexto para agentes de desenvolvimento

JUDAH é responsável pelo lifecycle operacional do Help Desk, filas, Matchmaker,
agentes, calendário, métricas, Celery, HubSpot e persistência compartilhada.

Não reintroduza identificação ou triagem no backend. O n8n assumirá coleta e
confirmação de identidade e triagem em uma etapa futura, com contrato ainda não
definido. Não antecipe endpoints, DTOs, flags ou placeholders.

Preserve `apps/support`, o ledger de `apps/ai_agents`, HubSpot compartilhado,
RAG, knowledge e Salomão independente. Execute testes somente com isolamento
local seguro.

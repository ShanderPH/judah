# Decisões arquiteturais

## ADR-011: remover identificação e triagem legadas do JUDAH

- **Status:** aceito em 2026-08-22.
- **Contexto:** a implementação anterior de identificação, Heimdall, triagem e
  Supervisor não estava funcional nem ativa como arquitetura aprovada.
- **Decisão:** remover endpoints, agentes, prompts, serviços, tasks, estados,
  flags, assinaturas HubSpot e dependência MCP usados exclusivamente por esse
  fluxo. Preservar lifecycle, filas, Matchmaker, agentes, calendário, métricas,
  HubSpot compartilhado, RAG e Salomão independente.
- **Banco:** não apagar dados históricos. Uma migration forward-only bloqueia
  caso encontre trabalho legado ativo, estreita choices e remove apenas o job
  periódico legado conhecido.
- **Boundary futuro:** n8n será responsável por identificação, coleta e
  confirmação de dados e triagem; JUDAH continuará responsável por ingestão
  durável, contexto operacional, retries genéricos, lifecycle, filas,
  atribuição e métricas. A integração não é criada por esta decisão.
- **Consequências:** `/api/v1/ai/` deixa de existir, mensagens não acionam bot e
  a futura integração deverá ter contrato próprio aprovado.

## Decisões superseded

ADR-002 (Supervisor Agno), ADR-003 (Heimdall), ADR-004 (FastMCP para ações) e
ADR-005 (`AI_ROUTING_ENABLED`) estão superseded pelo ADR-011. Seus artefatos
executáveis foram removidos; o Git preserva o histórico.

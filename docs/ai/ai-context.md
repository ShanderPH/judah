> [Índice completo](../INDEX.md)

# Contexto do Projeto para Agentes de IA

## O que é o JUDAH

O JUDAH é o backend unificado da InChurch. Ele consolida múltiplos sistemas legados em uma única plataforma para:

- Autenticação e gerenciamento de usuários (`auth_user`).
- Gestão de igrejas, planos e gateways (`church`).
- Base de conhecimento com busca semântica (`knowledge`).
- Atendimento ao cliente com fila e atribuição automática (`support`).
- Webhooks do HubSpot e Jira (`webhooks`).
- Agentes de IA (`ai_agents`).
- Analytics (`analytics`).
- Integrações (`integrations`).

## Arquitetura

- API REST com Django Ninja.
- Tarefas assíncronas com Celery.
- Cache e broker com Redis.
- Banco relacional PostgreSQL + vetorial Pinecone.
- Deploy no Railway.

## Regras de ouro

1. **Nunca** apague dados de produção sem aprovação.
2. **Sempre** use branches nomeadas como `<type>/<kebab-summary>`.
3. **Sempre** rode lint, type check e testes antes de abrir PR.
4. **Nunca** hardcode secrets.
5. **Sempre** marque incertezas como `TODO: confirmar`.

## Decisões arquiteturais importantes

- Fila de atendimento usa status do HubSpot (`NOVO`, `TRIAGE`, `ESCALADO`, `RESOLVIDO`).
- Atribuição automática considera carga, habilidades, prioridade e horário de trabalho.
- IA funciona como assistente (`Salomão`) e supervisor (`Heimdall`).
- `AI_ROUTING_ENABLED` controla se rotas `/api/v1/ai/` são montadas.

## Documentação complementar

- [`architecture/overview.md`](../architecture/overview.md)
- [`services/support.md`](../services/support.md)
- [`services/ai_agents.md`](../services/ai_agents.md)

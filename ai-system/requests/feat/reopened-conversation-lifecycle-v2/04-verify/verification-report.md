# Relatório de verificação

Data: 2026-07-31
Base: `main` em `3e3c0d9`
Branch local: `feat/reopened-conversation-lifecycle-v2`

## Resultado funcional

- Conversa fechada reabre na mesma `ConversationInstance`.
- `closed_at` e o agente corrente antigo são limpos na reabertura.
- Um novo ciclo aberto, com sequência e chave de idempotência próprias, é criado exatamente uma vez.
- Redelivery do mesmo webhook não cria outro ciclo.
- Supervisor e Salomão-V1 recebem contexto tipado de reabertura e histórico recente.
- Eventos, transições, execuções, ferramentas e custos novos apontam para o ciclo vigente.
- Uma instância aceita vários atendentes e preserva o mesmo agente em ciclos diferentes.
- Atribuição automática, manual, owner change e reatribuição forçada gravam o histórico.

## Comandos e evidências

- Testes focados de lifecycle/HubSpot/atendentes: `120 passed`.
- Testes de migration histórica + protocolo + workflow: `58 passed`.
- Suíte completa final: `1045 passed, 12 skipped` em SQLite local descartável.
- `ruff check apps/ai_agents apps/support`: passou.
- `ruff format --check`: passou após formatação.
- `mypy apps/ai_agents apps/support`: passou em 205 arquivos.
- `manage.py check`: nenhum problema.
- `makemigrations --check --dry-run`: nenhuma alteração pendente.
- Aplicação, reversão e reaplicação das migrations `ai_agents.0007` e `support.0027`: passou.
- `git diff --check`: passou.

Os 12 skips da suíte completa são integrações que exigem PostgreSQL/Redis local e já eram condicionais no repositório; não representam falha desta mudança.

## Observação de deploy

As migrations precisam ser aplicadas antes de iniciar workers com o novo código. Em Supabase/PostgreSQL, use a conexão de migration proprietária para que a proteção RLS das duas tabelas seja aplicada. Não há variável de ambiente nova.

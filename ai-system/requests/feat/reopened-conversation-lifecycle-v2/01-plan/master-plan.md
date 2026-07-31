# Plano — lifecycle de conversas reabertas v2

## Critérios de aceitação

1. Webhooks de mensagem e de estágio reabrem uma instância fechada somente após a rota HubSpot ser validada.
2. A mesma `ConversationInstance` volta para um estado aberto e limpa `closed_at`.
3. Cada reabertura cria exatamente um novo ciclo de serviço e uma nova chave de idempotência; retries e redeliveries não criam ciclos adicionais.
4. O Supervisor, Heimdall e Salomão-V1 recebem histórico e metadados tipados de reabertura antes da decisão.
5. Eventos, transições, execuções de agentes, efeitos e custos novos ficam associados ao ciclo de serviço correto.
6. Uma instância pode registrar vários atendentes, sem apagar agentes de ciclos anteriores ou reatribuições do ciclo atual.
7. A identidade canônica da thread e as chaves de deduplicação de webhook continuam estáveis.
8. Migrations são aditivas/reversíveis e não exigem backfill destrutivo.
9. Regressões de lifecycle, HubSpot, Matchmaker, owner change e métricas ficam cobertas por testes.

## Implementação

- Criar `ConversationServiceCycle` no domínio de IA com sequência, estado e UUID de idempotência.
- Ligar os ledgers de evento, transição, execução, ferramenta e custo ao ciclo por FKs opcionais.
- Centralizar abertura, fechamento, reabertura e contexto do ciclo em serviço transacional.
- Tornar `LifecycleEngine.transition()` consistente com o ciclo e associar cada ocorrência ao ciclo efetivo.
- Incluir dados de reabertura no `ConversationContext` e nos prompts enviados ao Supervisor/Salomão-V1.
- Criar `ConversationInstanceAttendant` em `support`, relacionado à instância, ciclo e `Agent`.
- Registrar atendentes em atribuição automática/manual, owner change e reatribuição forçada.
- Manter `assigned_agent_id` apenas como projeção compatível do proprietário atual.

## Verificação

- Testes focados em SQLite local isolado.
- Suite completa somente com banco local descartável conforme guardrail do repositório.
- Ruff, format, mypy, Django checks, migration drift e `git diff --check`.

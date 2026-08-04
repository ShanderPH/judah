# Estado atual — conversas reabertas

- A `main` já recebe `conversation.newMessage`, mudanças de `hs_pipeline_stage` e entradas calculadas nos estágios de IA, Novo e Fechado.
- `ConversationInstance` pode sair de `CLOSED` para `CONTEXT_HYDRATING` ou `QUEUE_PENDING`, limpando `closed_at`.
- A identidade canônica da instância é a thread HubSpot; reutilizá-la é correto para preservar o ledger completo.
- A chave operacional da instância não muda em uma reabertura, portanto métricas de IA não distinguem dois atendimentos na mesma thread.
- `assigned_agent_id` preserva apenas o agente corrente/mais recente; não existe relacionamento normalizado de todos os agentes que atenderam a instância.
- O Supervisor recebe histórico recente, mas não recebe um sinal tipado indicando que o turno pertence a uma reabertura.

## Decisão

Preservar a `ConversationInstance` canônica e criar ciclos de serviço imutáveis, um por atendimento. Cada ciclo possui chave de idempotência própria. Eventos, transições, execuções, ferramentas e custos podem apontar para o ciclo correspondente. O relacionamento de atendentes será histórico e many-per-instance, qualificado pelo ciclo.

# Decision log — lifecycle de conversas reabertas v2

## Identidade canônica e identidade do atendimento

A `ConversationInstance` continua representando a thread canônica do HubSpot. Reabrir não cria outra instância e não troca sua chave de deduplicação, evitando threads duplicadas e perda de histórico.

Cada período de atendimento é representado por `ConversationServiceCycle`. O ciclo possui sequência crescente e um UUID v5 próprio, derivado de `(instance_id, sequence)`. Isso dá uma identidade idempotente, reproduzível e diferente para cada reabertura, sem tornar retries do mesmo evento em novos atendimentos.

## Concorrência e reabertura

Transições bloqueiam a instância com `select_for_update`. A restrição parcial `uniq_open_conv_service_cycle` garante no banco que exista no máximo um ciclo aberto por instância, enquanto `uniq_conv_service_cycle_sequence` protege a ordem. A transição terminal → aberta fecha o ciclo anterior, abre o próximo, limpa `closed_at` e remove a projeção do agente anterior.

## Métricas e auditoria

Eventos, transições, execuções de agentes, ferramentas e custos receberam FK opcional para o ciclo. O campo é opcional para preservar registros históricos sem backfill destrutivo. Todo registro novo criado pelos fluxos operacionais passa a ser correlacionado ao ciclo vigente.

As chaves de ações do Supervisor e do adaptador Salomão-V1 incorporam a chave do ciclo. A sessão/thread permanece estável para preservar contexto conversacional, mas os efeitos e as métricas de uma reabertura são independentes.

## Histórico 1:N de atendentes

`ConversationInstanceAttendant` registra agente, snapshots de nome/owner, origem e ciclo. A unicidade `(service_cycle, agent)` torna redeliveries idempotentes, permite vários agentes no mesmo ciclo e permite o mesmo agente novamente em ciclos posteriores. `assigned_agent_id` permanece apenas como projeção compatível do proprietário atual.

## Índices

- `(instance, status)`: leitura e bloqueio do ciclo aberto de uma instância.
- `(opened_at, status)`: métricas e reconciliação de ciclos por janela temporal.
- `(instance, first_seen_at)`: histórico cronológico de atendentes de uma conversa.
- `(agent, first_seen_at)`: histórico e métricas de atendimentos por agente.

## Segurança e rollout

As migrations são aditivas e reversíveis. As novas tabelas revogam privilégios de `anon`/`authenticated` e habilitam RLS quando a migration roda com conexão proprietária; em conexão sem autoridade, emitem aviso e não mascaram a necessidade da migration privilegiada. Nenhuma variável de ambiente nova foi introduzida.

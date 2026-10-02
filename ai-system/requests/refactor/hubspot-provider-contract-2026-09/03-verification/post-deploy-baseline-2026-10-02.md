# Baseline pós-deploy — 2026-10-02

## Objetivo

Estabelecer o baseline operacional após os PRs #130–#133, sem executar mutation HubSpot, replay, repair histórico, backfill ou novo deploy. Esta verificação serve como evidência para a Fase 4 do rollout e para atualizar os blockers de V-03/ARCH-03.

## Escopo e fontes

- GitHub `main`;
- deployments de produção no Railway;
- PostgreSQL de produção no Supabase, somente consultas read-only;
- código de reconciliação/lifecycle no SHA atual.

Cutoff operacional usado nas métricas pós-deploy: **2026-09-30 14:30 UTC**, imediatamente após a estabilização do worker no PR #133.

## Baseline de versão e deploy

- `main`: `0ca25b842ef55607af210419a8c17c4b56d6074f` — merge do PR #133.
- `judah`: deployment SUCCESS no SHA atual.
- `judah-worker`: deployment SUCCESS no SHA atual após duas tentativas anteriores com falha.
- `judah-beat`: deployment SUCCESS no SHA atual.
- Webhooks continuaram respondendo HTTP 202 durante a janela observada.
- Os valores das variáveis Railway não ficaram disponíveis nesta sessão por redaction do conector; não registrar seus valores por inferência.

## Schema e migration 0036

A migration `support.0036_assignment_log_provenance_check` está aplicada em produção desde **2026-09-30 13:44:01 UTC**.

O CHECK físico atual de `assignment_logs.assignment_type` aceita:

- `auto`
- `automatic`
- `manual`
- `automatic_assignment`
- `manual_assignment`
- `owner_change`
- `forced_reassignment`
- `external_integration`
- `unknown_external`

Distribuição observada na tabela no momento da verificação: 1.878 `automatic`, 50 `automatic_assignment`, 80 `manual` e 85 `unknown_external`.

## Roster pós-PR #133

Estado local do roster:

- 8 agentes ativos;
- 8 agentes ativos com `hubspot_owner_id`;
- 8 agentes ativos com `hubspot_user_id` CRM;
- 7 agentes ativos no time N1 `team_54655589`;
- 0 agentes N1 ativos sem `hubspot_owner_id`.

Não foi encontrado novo log `HubSpot user-to-owner mapping changed` na consulta Railway pós-deploy. Isso não substitui o preflight/readback formal, mas remove o sintoma que motivou o PR #133 no baseline observado.

## Invariantes que permaneceram verdes

No banco atual:

- 0 tickets com múltiplos ciclos simultaneamente não fechados;
- 0 tickets com múltiplas rows de occupancy;
- 0 ticket/cycle pós-cutover com múltiplos `AssignmentLog`;
- 0 agentes ativos com divergência entre `current_simultaneous_chats` e occupancy ativa + reservation held;
- 49 attempts automáticos pós-cutover chegaram a `completed / confirmed_by_read`;
- 1 attempt automático foi compensado como `stale_ticket`.

Materialização de provenance pós-cutover:

- 49 logs `automatic_assignment`, todos com cycle e attempt;
- 72 logs `unknown_external`, todos com cycle e sem attempt;
- 17 reassignments `unknown_external`, todos com cycle; `reassigned_at` permanece nulo por ausência de prova temporal externa.

Esses dados são compatíveis com a regra de não fabricar `AssignmentAttempt` nem timestamp para efeitos externos sem evidência.

## Backlog de lifecycle encontrado

Desde o cutoff foram observadas 849 ocorrências de lifecycle.

### Owner changed

- 332 `owner_changed / processed`;
- 229 `owner_changed / repair_required`;
  - 219 com `owner_cycle_pending`;
  - 10 com `CapacityObservationConflictError`.

Das 229 ocorrências em repair, **24 hoje já encontram um ciclo cujo intervalo temporal contém a ocorrência**, cobrindo 13 tickets.

O scanner `task_scan_lifecycle_occurrences` seleciona somente `processing_status=PENDING`. Portanto `repair_required` não retorna automaticamente à reconciliação mesmo que a evidência de ciclo apareça depois. Isso é comportamento coerente com o orçamento bounded, mas impede considerar convergência runtime comprovada até o backlog ser classificado e tratado por política explícita.

### Entrada na fila

Existem 3 ocorrências `entered_support_queue / pending / proven`:

- nenhuma possui ciclo exato correspondente;
- todas têm `next_reconcile_at = NULL`;
- todas têm `retry_count = 0`;
- nenhuma possui `last_error_code`;
- a mais antiga é de 2026-09-30 e a mais recente de 2026-10-01.

Como o scanner só busca pending com `next_reconcile_at <= now()`, essas três rows não entram no mecanismo de recuperação atual. Precisam ser investigadas antes do fechamento da Fase 4.

### Fechamento

Também permanecem em `repair_required`:

- 13 ocorrências `closed / no_cycle`;
- 2 ocorrências `closed / reopen_not_materialized`.

Elas devem ser classificadas junto ao backlog, sem inventar ciclo ou timestamp.

## Occupancy atual

A tabela possui 4 occupancies em estado `active`; 3 são rows históricas observadas antes do cutover e sem cycle/agent. No conjunto observado pós-cutover, existe 1 occupancy ativa com cycle e sem agent, cenário compatível com ticket ativo ainda não atribuído.

Para agentes ativos, a materialização de capacidade está consistente no instante da verificação: total calculado e total materializado são ambos zero.

## Conclusão da Etapa 1

A Etapa 1 **não encontrou evidência de double-write ou drift de capacidade** no baseline atual, e confirmou que PR #132/#133 e migration 0036 estão efetivamente em produção.

Entretanto, a Fase 4 ainda não pode ser considerada verde. O próximo blocker objetivo deixou de ser “deploy da 0036” e passou a ser **classificação/convergência do backlog de lifecycle**.

### Próximo gate

Antes de V-03/canário final, executar uma etapa dedicada a:

1. classificar os 229 `owner_changed repair_required`, começando pelos 24 agora temporalmente resolvíveis;
2. explicar/corrigir as 3 entradas `pending` sem agendamento;
3. classificar os 15 fechamentos em repair;
4. decidir, por classe, entre correção de código, repair bounded autorizado ou permanência explícita como evidência não projetável;
5. repetir as invariantes deste baseline após qualquer mudança.

Nenhum replay, repair, backfill, PATCH HubSpot ou alteração de dados foi executado nesta verificação.

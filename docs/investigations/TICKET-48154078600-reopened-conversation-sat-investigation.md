# Investigação — ticket HubSpot 48154078600 e reentrada no SAT

**Data da investigação:** 2026-09-04 09:28 BRT
**Escopo:** HubSpot, Supabase/PostgreSQL, Railway, GitHub e código implantado do JUDAH
**Modo:** somente leitura; nenhuma alteração de ticket, banco, variável, deploy ou workflow foi executada
**Ticket:** [48154078600 no HubSpot](https://app.hubspot.com/contacts/47354717/record/0-5/48154078600?utm_source=judah_investigation&utm_medium=internal&utm_campaign=ticket_48154078600)
**Thread:** `11154586391`
**Portal:** `47354717`

## 1. Conclusão executiva

A premissa de que a conversa **não entraria novamente no SAT não se confirmou em produção**.

O ticket foi reaberto pelo cliente às **05:04:02 BRT** de 04/09/2026. O HubSpot manteve o mesmo ticket e a mesma thread, mas publicou uma nova ocorrência de entrada no estágio NOVO, com timestamp próprio (`hs_v2_date_entered_939275049 = 2026-09-04T08:04:03.204Z`). O JUDAH recebeu e processou esse evento, criou um novo ciclo de atendimento, preservou a conversa na fila durante o período fora do expediente e a atribuiu automaticamente às **09:00:53 BRT** para **Gabriel Knust**.

Às **09:01:27 BRT**, aproximadamente 34 segundos depois, a conversa foi transferida de Gabriel para **Esther Finotti** dentro do Help Desk. O estado atual do ticket mostra Esther como owner e pode produzir a impressão de que o SAT nunca atuou. Entretanto, o ledger transacional do JUDAH, o histórico de atribuições da thread e os eventos de mudança de owner provam a atribuição automática anterior.

Portanto:

- não houve supressão da reabertura pelo ID antigo do ticket;
- não houve perda do webhook de reentrada;
- não houve bloqueio do SAT na abertura do expediente;
- a ausência atual de linha em `new_conversations` é consequência normal do consumo bem-sucedido da fila;
- a causa raiz da **percepção** de não atribuição é a reatribuição humana quase imediata após a atuação do SAT.

## 2. Resposta direta à dúvida sobre o mesmo ticket

O HubSpot preservou:

- ticket `48154078600`;
- thread `11154586391`;
- histórico integral de mensagens.

O JUDAH não depende apenas do ID do ticket para distinguir atendimentos reabertos. A ocorrência de suporte é identificada pelo conjunto:

```text
(source_system, portal_id, hubspot_ticket_id, entered_stage_at)
```

Neste caso, a entrada de 04/09/2026 às 05:04:03 BRT produziu o ciclo:

```text
support_conversation_cycle.id = 564523f7-b3e7-4b6f-b37e-cd0308823000
identity_source               = hubspot_stage_entry
source_event_id               = 1521761777
entered_stage_at              = 2026-09-04T08:04:03.204Z
state                         = assigned
```

Assim, manter o mesmo ticket no HubSpot não impediu a reentrada. A nova data comprovada de entrada no estágio foi a identidade da nova ocorrência.

## 3. Linha do tempo consolidada

Horários abaixo em BRT (`America/Sao_Paulo`, UTC-03:00).

| Data/hora BRT | Origem | Evento e efeito |
|---|---|---|
| 03/09 13:53:55 | HubSpot | Esther inicia contato proativo. Thread e ticket são criados já atribuídos a Esther. |
| 03/09 13:57:11 | Cliente | Primeiro retorno: informa que está disponível. |
| 03/09 13:57–14:01 | Esther | Explica a análise sobre usuários do app, ausência de invasão, desvinculação de perfis e proposta de moderação/aprovação. |
| 03/09 16:59:15 | Esther | Solicita confirmação de leitura. |
| 03/09 18:07:16 | HubSpot | Thread fechada e owner removido. |
| 03/09 18:24:04 | Esther | Envia mensagem de encerramento do horário e pede retorno no dia seguinte. A mensagem reabre momentaneamente a thread. |
| 03/09 18:24:20 | HubSpot | Thread/ticket fechados novamente e owner removido. Este é o fechamento efetivo anterior à reabertura do cliente. |
| 04/09 05:04:02 | Cliente | Cliente responde: vai analisar e pede desculpas por não ter visto antes. A mesma thread é reaberta. |
| 04/09 05:04:03 | HubSpot | Ticket entra novamente no estágio NOVO (`939275049`). Evento `1521761777`. |
| 04/09 05:04:13 | JUDAH | Webhook processado; novo ciclo de suporte e novo ciclo de serviço são abertos. Estado lógico: `QUEUE_PENDING`. |
| 04/09 05:04–09:00 | JUDAH | Fora do horário operacional. A fila é preservada; não há tentativa externa de owner. |
| 04/09 07:24:19 | Cliente | Contesta a classificação como change request e pede próximos passos. |
| 04/09 07:29:55 | Cliente | Acrescenta que os perfis estavam ligados à igreja local Gaia. |
| 04/09 09:00:51 | JUDAH | Reserva transacional da tentativa automática. |
| 04/09 09:00:53 | JUDAH → HubSpot | Owner `970530315` aplicado e confirmado por leitura: Gabriel Knust. |
| 04/09 09:00:53 | HubSpot | Thread registra `assignedTo=A-72733598`, correspondente à atribuição recém-aplicada. |
| 04/09 09:01:27 | Help Desk | A thread registra transferência do ator então atribuído para `A-89931616` (Esther). O ticket muda de owner para `89931616`. |
| 04/09 09:02:13 | Esther | Informa que seguirá com o atendimento. |
| 04/09 09:12:43 | Esther | Informa que enviará um retorno. |
| 04/09 09:23:02 | Cliente | Confirma que está aguardando. |

## 4. Evidência HubSpot

### 4.1 Estado atual do ticket

Snapshot às 09:23 BRT:

- `hs_pipeline = 636459134`;
- `hs_pipeline_stage = 939275049` (NOVO);
- `hs_ticket_reopened_at = 2026-09-04T08:04:03.204Z`;
- `hs_last_closed_date = 2026-09-03T21:24:20.189Z`;
- `hs_last_message_received_at = 2026-09-04T12:23:02.087Z`;
- `hubspot_owner_id = 89931616` (Esther Finotti);
- `hubspot_owner_assigneddate = 2026-09-04T12:01:26.816Z`;
- `hs_object_source_label = CONVERSATIONS`;
- `hs_ticket_owner_type = human_rep`;
- `source_type` não foi necessário para determinar a cadeia causal.

### 4.2 Estado atual da thread

- status: `OPEN`;
- ticket associado: `48154078600`;
- última mensagem: `2026-09-04T12:23:02.087Z`;
- atribuição atual: Esther;
- 28 registros de mensagem/sistema recuperados em uma única página, sem paginação restante.

### 4.3 Prova da atribuição e reatribuição

O histórico da thread contém, nesta ordem:

1. `2026-09-04T12:00:53.776Z`: evento `ASSIGNMENT`, `assignedTo=A-72733598`;
2. `2026-09-04T12:01:27.322Z`: evento `ASSIGNMENT`, criado pelo ator que estava atribuído, transferindo de `A-72733598` para `A-89931616`;
3. `2026-09-04T12:02:13.446Z`: Esther envia “vou seguir com o seu atendimento”.

O CRM confirma os owners:

- `970530315` → Gabriel Knust;
- `89931616` → Esther Finotti.

A associação entre o ator de thread `A-72733598` e Gabriel é uma inferência de alta confiança pela coincidência temporal com a alteração confirmada do owner para Gabriel e pela transferência subsequente a Esther. Os IDs de ator da Conversations API e os IDs de owner do CRM pertencem a namespaces diferentes.

## 5. Evidência Supabase/PostgreSQL

### 5.1 Ingestão do evento de reabertura

`webhook_events` contém:

```text
id                = 2eb7e274-e37a-4289-b930-1cf484504fb8
event_id          = 1521761777
object_id         = 48154078600
property_name     = hs_v2_date_entered_939275049
property_value    = 1788509043204
received_at       = 2026-09-04T08:04:12.237438Z
processed         = true
processed_at      = 2026-09-04T08:04:13.349480Z
processing_status = RECEIVED
error_message     = null
```

O evento de mensagem do cliente imediatamente anterior também está hidratado:

```text
thread_id         = 11154586391
ticket_id         = 48154078600
message_id        = fc9d07145a62f3f9ea8acf9a3d066822
occurred_at       = 2026-09-04T08:04:02.398Z
processing_status = READY
ignored_reason    = vazio
```

### 5.2 Ciclo de suporte e permanência na fila

O ciclo foi aberto com estado `queued` a partir da ocorrência de 05:04:03 BRT e atualizado para `assigned` às 09:00:53 BRT.

O tempo registrado de espera foi `14209.94` segundos, equivalente a **3h56m49,94s**. A diferença entre a entrada (`05:04:03.204`) e a atribuição (`09:00:53.139`) coincide exatamente com esse valor. Isso é prova de que a ocorrência permaneceu durável até a abertura, em vez de ser descartada.

### 5.3 Tentativa de atribuição

```text
assignment_attempt.id            = 55aa124b-0ab6-4e57-b586-0e28aa9c2e6a
state                            = completed
assignment_type                  = automatic
decision_reason                  = eligible
desired_hubspot_owner_id         = 970530315
prior_observed_owner_id          = null
provider_request_classification  = hubspot_owner_update
provider_result_classification   = confirmed_by_read
reserved_at                      = 2026-09-04T12:00:51.829796Z
external_applied_at              = 2026-09-04T12:00:53.053907Z
finalized_at                     = 2026-09-04T12:00:53.139422Z
retry_count                      = 0
last_error_code                  = vazio
cycle_id                         = 564523f7-b3e7-4b6f-b37e-cd0308823000
```

O snapshot da decisão registrou Gabriel com dois chats antes da reserva, limite de dez e revisão de disponibilidade `5494`.

### 5.4 Projeções persistidas

`assigned_conversations` e `assignment_logs` registram:

- agente: Gabriel Knust;
- owner: `970530315`;
- tipo: `automatic`;
- horário: 09:00:53 BRT;
- espera: `14209.94` segundos;
- mesmo `cycle_id` da reabertura.

Não existe linha atual em `new_conversations` para o ticket. Isso é esperado: ao finalizar uma atribuição confirmada, `finalize_assignment_attempt()` cria/atualiza as projeções de atribuída, grava o log, apaga a linha consumida da fila e deixa `assignment_attempt.queue_row_id = null`. A ausência da linha é prova de consumo, não de ausência de entrada.

### 5.5 Lifecycle paralelo

O `ConversationInstance` do ticket é `cdcb213b-ec3d-423d-8c3e-3101569a2a7c`.

O primeiro ciclo de serviço:

- abriu em 03/09 às 13:54 BRT;
- permaneceu em `QUEUE_PENDING` apesar de o ticket proativo já ter owner;
- foi marcado `FAILED_RETRYABLE` pelo watchdog;
- terminou `FAILED_TERMINAL` às 19:25:45 BRT por esgotamento do retry budget.

Na reabertura de 04/09, o evento `1521761777` abriu corretamente o ciclo de serviço de sequência 2:

```text
sequence          = 2
status            = OPEN
opened_from_state = FAILED_TERMINAL
opened_reason     = Ticket entered the support N1 assignment stage.
```

Às 09:00:53 BRT, o lifecycle mudou de `QUEUE_PENDING` para `HUMAN_ASSIGNED` com ator `matchmaker` e owner Gabriel.

O erro antigo do watchdog permanece no campo `current_error`, embora o estado atual seja `HUMAN_ASSIGNED`. Trata-se de inconsistência de observabilidade/limpeza de estado, não do bloqueador da atribuição desta reabertura.

## 6. Evidência Railway

### 6.1 Versão implantada

Os três serviços estavam online e alinhados no commit:

```text
d55e9a4f39fbff043fc7176a4059b27ea7276932
```

Serviços e deployments ativos:

- API `judah`: `b38f11f6-baa6-4977-9e4a-fce4eb5680ed`;
- worker `judah-worker`: `70ac1944-0dbd-42eb-9619-eba1883babe3`;
- beat `judah-beat`: `ea2991a2-1bfb-468d-84b7-103240e63812`.

O commit corresponde ao merge do PR #117 e contém os PRs anteriores de ciclos reabertos e correção do enum do SAT.

### 6.2 Configuração efetiva

Leitura das settings no ambiente production:

```text
AUTO_ASSIGNMENT_ENABLED=true
CONVERSATION_CYCLES_ENFORCED=false
HUBSPOT_PORTAL_ID=47354717
HUBSPOT_SUPPORT_NEW_STAGE_ID=939275049
HUBSPOT_SUPPORT_CLOSED_STAGE_ID=939275052
TIME_ZONE=America/Sao_Paulo
```

`CONVERSATION_CYCLES_ENFORCED=false` significa que o sistema ainda opera em dual-write compatível com o fluxo legado; não significa que ciclos estejam desativados. O caso foi gravado com `cycle_id` em todas as projeções relevantes.

### 6.3 Readiness

Às 09:28:24 BRT, `GET /api/v1/health/ready` retornou HTTP 200:

- database/cache/auth/JWT: `ok`;
- runtime de produção autoritativo: `true`;
- auto assignment: `true`;
- eligibility fail-closed: aplicada;
- migrations de ciclo: aplicadas;
- `queued_without_dispatch = 0`;
- `projection_mismatches = 0`.

A readiness global de enforcement de ciclos é `false` porque ainda existem linhas legadas sem ciclo e writers legados detectados. Isso é dívida de rollout global, mas não impediu este caso.

### 6.4 Limitação dos logs

`railway deployment list` e a leitura efetiva do ambiente funcionaram. As consultas históricas de logs da API e do worker retornaram `Unauthorized. Please login with railway login`. Depois de duas respostas idênticas, não houve nova tentativa nem reautenticação, para manter a investigação read-only e evitar abrir um fluxo de credencial sem autorização adicional.

Essa limitação não impede a conclusão: a tentativa transacional, a aplicação externa confirmada por leitura, as projeções e o histórico da thread fornecem evidência mais forte que uma linha de log isolada.

## 7. Evidência GitHub e comportamento implementado

### PR #81 — ciclos de atribuição para conversas reabertas

[PR #81](https://github.com/ShanderPH/judah/pull/81) introduziu ciclos explícitos porque a idempotência por ticket tratava reaberturas legítimas como já processadas. O desenho passou a escopar a identidade pela ocorrência comprovada de entrada no estágio NOVO.

### PR #102 — ciclos de serviço da mesma thread

[PR #102](https://github.com/ShanderPH/judah/pull/102) permitiu reabrir a mesma `ConversationInstance`, criar uma nova `ConversationServiceCycle` e separar idempotência, histórico e agentes por atendimento.

### PR #116 — correção do SAT

[PR #116](https://github.com/ShanderPH/judah/pull/116) removeu o erro PostgreSQL de escrita em enum que revertia o heartbeat do SAT. O deploy atual já contém essa correção e a tentativa deste ticket terminou sem erro.

### Caminho de código atual

1. `apps/webhooks/handlers/hubspot_handler.py:91-112` recebe a nova entrada no estágio e agenda `task_matchmaker_assign_single` após commit.
2. `apps/support/tasks.py:94-197` cria/preserva a fila; se o heartbeat detectar período fora do expediente, retorna sem remover a conversa.
3. `apps/support/matchmaker_service.py:317-412` valida pipeline, estágio e owner, cria o ciclo pela ocorrência e insere a fila.
4. `apps/support/auto_assign_service.py:150-193` exige ticket sem owner no estágio NOVO.
5. `apps/support/durable_assignment_service.py:650-713` confirma a atribuição, grava ledger/projeções, apaga a fila consumida e move o ciclo para `assigned`.

## 8. Causa raiz

### Causa raiz observada neste caso

**Não existe falha de reentrada ou de atribuição automática neste ticket.** A causa raiz da aparência de falha foi:

> O SAT atribuiu automaticamente a conversa para Gabriel às 09:00:53 BRT, mas a própria conversa foi transferida para Esther às 09:01:27 BRT. Como o HubSpot exibe o owner atual e a fila consumida é apagada, uma inspeção posterior sem consultar o ledger faz parecer que o SAT não processou a reabertura.

### Causa histórica que poderia ter produzido o sintoma

Antes do PR #81, a identidade ticket-wide poderia considerar uma reabertura do mesmo ticket como duplicada. Essa deficiência foi corrigida com a identidade por ocorrência de estágio. O deploy atual contém a correção e este ticket é uma evidência real de funcionamento.

### Condição que realmente impediria uma futura reentrada

Uma futura ocorrência pode deixar de abrir um ciclo quando:

- não houver timestamp comprovável de entrada no estágio;
- o ticket estiver fora do pipeline/estágio configurado;
- o ticket já possuir owner quando o JUDAH fizer o readback;
- houver um ciclo de suporte anterior ainda ativo, gerando `active_conflict`;
- a autoridade de ingestão/atribuição estiver desabilitada;
- o SAT não tiver agente elegível/capacidade, caso em que a fila deve permanecer aguardando.

Nenhuma dessas condições bloqueou a ocorrência de 04/09. No momento da reserva, o ticket não tinha owner, o ciclo era válido, a flag estava ligada e Gabriel estava elegível.

## 9. Achados secundários e riscos

### 9.1 Lifecycle antigo terminou por watchdog

O primeiro ciclo do `ConversationInstance` terminou por watchdog e não por fechamento normal. Além disso, `current_error` conserva a mensagem antiga mesmo depois de `HUMAN_ASSIGNED`. Recomenda-se uma investigação separada sobre fechamento e limpeza de erro do lifecycle. Isso não deve ser tratado como causa do SAT neste ticket.

### 9.2 Enforcement de ciclos ainda não está pronto globalmente

Embora este ticket tenha cobertura de ciclo completa, a readiness reporta linhas legadas e writers legados. Ativar `CONVERSATION_CYCLES_ENFORCED=true` exige o rollout/backfill previsto no PR #81 e uma decisão separada. Nenhuma mudança foi feita nesta investigação.

### 9.3 RLS em tabelas de calendário

O MCP do Supabase reportou RLS desabilitado em:

- `helpdesk_schedules`;
- `helpdesk_schedule_rules`;
- `helpdesk_schedule_intervals`;
- `helpdesk_absence_messages`.

É um achado de segurança independente do ticket e do SAT. Não foi aplicada correção, pois habilitar RLS sem políticas adequadas pode interromper o runtime e exige escopo/planejamento próprios.

## 10. Recomendações

1. Não executar replay, reatribuição, backfill ou correção manual neste ticket: o atendimento está aberto, atribuído e em andamento com Esther.
2. Para auditorias futuras, consultar `assignment_attempts`, `assignment_logs` e `assigned_conversations` antes de concluir pela ausência do SAT; `new_conversations` só representa fila ainda não consumida.
3. Tratar a transferência Gabriel → Esther como decisão operacional humana. Se a intenção for preservar continuidade com o owner anterior, definir essa regra explicitamente fora do algoritmo FIFO atual.
4. Abrir investigação separada para o lifecycle que terminou por watchdog e manteve `current_error` obsoleto.
5. Planejar separadamente o gate de enforcement dos ciclos e o hardening de RLS das tabelas de calendário.

## 11. Veredito

**Status:** atribuição automática comprovada.
**Reentrada:** comprovada.
**Fila fora do horário:** preservada.
**Atribuição no início do expediente:** concluída às 09:00:53 BRT.
**Owner atual diferente do escolhido pelo SAT:** resultado de reatribuição posterior para Esther.
**Correção emergencial necessária para este ticket:** não.
**Débitos separados:** lifecycle/watchdog, rollout global de enforcement de ciclos e RLS do calendário.

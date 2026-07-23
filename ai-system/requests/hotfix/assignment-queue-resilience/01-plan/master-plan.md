# Plano de implementação — resiliência da fila de atribuição

**Request:** `hotfix/assignment-queue-resilience`
**Branch:** `hotfix/assignment-queue-resilience`
**Ciclo/Fase:** F / PLAN
**Base:** `00-context/research.md` e diagnóstico de produção de 23/07/2026
**Implementação:** não iniciada
**Deploy ou nova mutação em produção autorizados:** não

## 1. Resultado esperado

Transformar o Matchmaker em um consumidor com progresso garantido por item:
qualquer conversa selecionada deve sair daquele ciclo de processamento como
atribuída, convergida, deferida ou quarentenada. Nenhuma inconformidade local
pode bloquear os itens seguintes.

O hotfix preservará o protocolo durável `reserve -> apply -> finalize /
compensate / repair`, a autoridade do HubSpot para owner/presença, a autoridade
do JUDAH para ciclo/fila e o veto de ausência imediatamente antes da atribuição.

## 2. Invariantes obrigatórias

1. Um item é processado no máximo uma vez por execução do drain.
2. `assigned` aumenta somente após uma nova mutação de owner confirmada e um
   finalize novo; convergência/no-op possui contador próprio.
3. `assigned <= total_pending` e `remaining <= total_pending + admitted`.
4. Cada resultado inclui `queue_row_id`, `cycle_id`, outcome tipado e
   `made_progress`, sem PII nos logs agregados.
5. Todo item selecionado termina em uma destas classes:
   `assigned`, `converged`, `quarantined`, `deferred`, `claimed_elsewhere`.
6. Dado inválido ou legado ambíguo é isolado e o drain continua.
7. Falha sistêmica preserva a fila e interrompe efeitos externos; não transforma
   todos os itens em inválidos.
8. Tentativa `completed` de ciclo anterior nunca conclui um ciclo novo.
9. Owner manual confirmado nunca é sobrescrito por autoatribuição posterior.
10. HubSpot nunca é chamado dentro de transação PostgreSQL longa.
11. Locks Redis são otimização; correção e idempotência residem no PostgreSQL.
12. Reprocessamento, redelivery e concorrência não duplicam capacidade, log,
    projeção, métrica ou owner update.

## 3. Contrato de outcomes

Criar um contrato tipado, por exemplo `QueueItemOutcome` (`StrEnum`) e
`QueueItemResult` (`dataclass(frozen=True, slots=True)`), com ao menos:

```text
ASSIGNED_NEW_EFFECT
CONVERGED_COMPLETED
CONVERGED_EXTERNAL_OWNER
QUARANTINED_LEGACY_AMBIGUOUS
QUARANTINED_STALE_CYCLE
QUARANTINED_PERMANENT_PROVIDER_ERROR
DEFERRED_NO_AGENT
DEFERRED_CANDIDATE_CHANGED
DEFERRED_PROVIDER_TRANSIENT
CLAIMED_ELSEWHERE
QUEUE_EMPTY
SYSTEMIC_FAILURE
```

`made_progress=true` exige uma transição persistida ou consumo seguro da linha.
`effect_applied=true` existe somente quando houve nova mutação externa.

## 4. Work breakdown

### Gate A — contrato e seleção progressiva

#### BE-01 — Resultado tipado por item

- Substituir strings ambíguas entre `reserve_next_assignment()`,
  `execute_assignment_attempt()` e Matchmaker por outcomes explícitos.
- Diferenciar `completed` histórico, tentativa viva, fila ocupada, ciclo stale,
  candidato alterado e falha sistêmica.
- Nunca mapear tentativa previamente `completed` para nova atribuição.

**Alvos:**

- `apps/support/durable_assignment_service.py`
- `apps/support/matchmaker_service.py`
- testes unitários correspondentes

**Aceite:** chamada idempotente não incrementa `assigned`; todos os retornos são
exaustivos e checados pelo mypy.

#### BE-02 — Drain com progresso garantido

- Processar lote limitado, mantendo `seen_queue_row_ids` na execução.
- Permitir exclusão dos IDs já vistos na próxima seleção.
- Usar `select_for_update(skip_locked=True)` em transação curta por item.
- Continuar após convergência, quarentena, defer e claim concorrente.
- Encerrar somente em fila vazia, limite do lote ou falha sistêmica.
- Detectar `made_progress=false` repetido e emitir `queue_drain_no_progress`.
- Separar contadores `assigned`, `converged`, `quarantined`, `deferred`,
  `claimed_elsewhere`, `systemic_failures` e `remaining`.

Não usar um `atomic()` externo envolvendo o lote. Cada item terá seu próprio
savepoint/transação e qualquer efeito HubSpot ficará fora do lock do banco.

**Aceite:** um item venenoso na primeira posição não impede o segundo; nenhum
ID é selecionado duas vezes no mesmo drain; métricas impossíveis falham teste.

### Gate B — legado, ciclo e owner externo

#### BE-03 — Convergir completed/orphan com segurança

Para fila com ciclo:

- lock da fila, ciclo e tentativa do mesmo `cycle_id`;
- se tentativa concluída pertence ao ciclo, validar projeção;
- consumir fila residual e transicionar ciclo/projeção se seguro;
- retornar `CONVERGED_COMPLETED`, nunca `ASSIGNED_NEW_EFFECT`.

Para fila sem ciclo:

- tentativa por `ticket_id` não é prova de mesma ocorrência;
- não reutilizar idempotency key ticket-wide para novo efeito;
- se não houver identidade comprovável, quarentenar com
  `legacy_cycle_ambiguous` e continuar;
- recuperação de identidade deve usar timestamp NOVO comprovado ou o backfill
  existente, nunca `timezone.now()`.

**Aceite:** tentativa histórica não bloqueia reabertura; legado ambíguo não
recebe owner automaticamente e não bloqueia a fila.

#### BE-04 — Reconciliação de atribuição manual

Criar serviço canônico de reconciliação de owner externo:

- tratar owner webhook mesmo quando `previousValue` está ausente;
- localizar e travar fila/ciclo ativo;
- confirmar owner atual no HubSpot em caso de evento ambíguo/out-of-order;
- se já há owner, remover/convergir a fila sem chamar `assign_ticket_owner()`;
- criar/atualizar projeção e capacidade de forma idempotente;
- registrar origem `hubspot_manual` e preservar histórico;
- redelivery do webhook torna-se no-op comprovado.

**Alvos:**

- `apps/support/tasks.py`
- `apps/support/auto_assign_service.py` ou novo serviço coeso em `apps/support/`
- `apps/webhooks/handlers/hubspot_handler.py` apenas se o contrato exigir dados
  adicionais, sem alterar verificação HMAC

**Aceite:** owner manual enquanto queued elimina dispatch local, não é
sobrescrito e não duplica contagem.

#### DATA-01 — Reconciliar ciclos queued sem dispatch

- Estender o comando de backfill/reconciliação existente com `--dry-run`,
  `--limit`, cursor e relatório agregado sem PII.
- Classificar os 17 ciclos atuais por owner/estágio: já atribuídos, ainda NOVO
  sem owner, fechados, ambíguos.
- Nenhuma consulta HubSpot ou write de produção ocorre sem aprovação separada.
- Aplicação real deve ser reiniciável e idempotente por ciclo.

**Stop gate:** dry-run revisado antes de qualquer reparo compartilhado.

### Gate C — elegibilidade, locks e retry

#### BE-05 — Revisão somente por mudança material

- Definir fingerprint/material fields de elegibilidade.
- Incrementar `availability_revision` somente se a decisão material mudar.
- Atualizar heartbeat, frescor e fencing em campos independentes.
- Após lock do agente, reavaliar estado atual; se continua materialmente
  equivalente, aceitar mesmo que apenas frescor tenha mudado.
- Mudança material real retorna defer com retry curto e limitado.

**Aceite:** heartbeat idêntico não invalida candidato; away/out-of-office,
capacidade e permissão continuam invalidando imediatamente.

#### BE-06 — Locks como otimização owner-safe

- Remover o lock global Redis como requisito de correção do drain; concorrência
  será serializada por claims, constraints e `SKIP LOCKED`.
- Onde coalescência Redis continuar útil, usar cliente redis-py dedicado e Lua
  compare-and-delete por token, sem depender de API privada do cache Django.
- Falha ao liberar lock gera métrica, mas não deixa o item invisível.
- TTL permanece apenas como recuperação de crash.

**Aceite:** dois drains concorrentes processam linhas distintas; crash libera
por TTL; caminho normal libera imediatamente; token alheio nunca remove lock.

#### BE-07 — Taxonomia Celery e reagendamento

- Retry automático apenas para exceções transitórias explícitas.
- Configurar backoff limitado, jitter e máximo de tentativas por task.
- `skipped_locked`, `candidate_changed` e indisponibilidade transitória devem
  agendar retry curto; não depender só do Beat de 60 segundos.
- Erro permanente de item vira quarentena, não retry da task inteira.
- Falha sistêmica abre circuito/preserva fila e mantém stack trace.
- Avaliar `acks_late`/`reject_on_worker_lost` somente depois que os testes de
  idempotência do protocolo durável estiverem verdes; não mudar globalmente.

### Gate D — observabilidade e controles operacionais

#### OPS-01 — Readiness de progresso

Adicionar sinais agregados e sem PII:

- `ready_queue_depth` e idade do item pronto mais antigo;
- `poisoned_queue_rows` por classe;
- `completed_attempt_queue_conflicts`;
- `queued_without_dispatch`;
- `expired_claims`;
- último drain: duração e contadores por outcome;
- `no_progress_drains` e violação `assigned > total_pending`;
- owner reconciliation backlog.

Fila com item problemático isolável degrada o componente e alerta, mas não
derruba o writer. Banco indisponível, migration ausente ou tentativa durável
presa continuam condições `unhealthy`.

#### OPS-02 — Runbook de recuperação

Atualizar `docs/operations/absence-safe-assignment.md` com:

- diagnóstico Supabase/Railway na ordem correta;
- dry-run de reconciliação;
- quarentena não destrutiva;
- drain controlado;
- verificação de owner HubSpot;
- limites de autoridade para DB, flags e deploy;
- procedimento para fila limpa sem apagar histórico.

### Gate E — migration e compatibilidade

O P0 deve reutilizar `queue_status`, `failure_code`, `next_assignment_attempt_at`,
claims e ciclos existentes. A expectativa é **não criar migration**.

Se a implementação provar necessidade de nova chave de idempotência/auditoria:

- parar no gate;
- criar migration expansiva, reversível e compatível com versão anterior;
- aplicar via caminho privilegiado Supabase, nunca pelo runtime Railway;
- documentar índice e impacto de lock;
- testar apply/reverse/reapply em PostgreSQL 16.

Nenhuma constraint ticket-wide será reintroduzida.

## 5. Plano de testes

### V-01 — Unitários de outcome/progresso

- completed do mesmo ciclo -> `converged`, fila consumida, zero owner call;
- completed de ciclo anterior -> não converge ciclo novo;
- legado ambíguo -> quarentena e próximo item processado;
- stale cycle, 404, 409/422, timeout, 429 e 5xx classificados;
- `assigned` só cresce para efeito novo;
- ausência de progresso encerra com alerta e sem loop.

### V-02 — Regressão de drain

- item venenoso na posição 1 + itens válidos 2..N;
- vários itens venenosos intercalados;
- defer do primeiro não bloqueia os seguintes;
- `assigned <= total_pending` em property/table-driven tests;
- lote limitado e próxima execução retoma corretamente;
- fila vazia e somente itens claimed/deferred.

### V-03 — Concorrência PostgreSQL 16

- dois workers drenando simultaneamente com `SKIP LOCKED`;
- single webhook concorrendo com drain;
- manual owner concorrendo com reserva/finalize;
- SAT atualizando agente durante seleção;
- crash após reserve, após HubSpot e antes do finalize;
- lock/claim expirado retomado uma única vez;
- repetir cenários para detectar flakiness.

Esses testes devem usar PostgreSQL 16 e Redis 7 descartáveis. SQLite não valida
locks, constraints parciais ou `SKIP LOCKED`.

### V-04 — Owner manual e ciclos

- owner inicial sem `previousValue` converge fila queued;
- redelivery idempotente;
- evento antigo não altera ciclo novo;
- owner externo já presente impede auto-owner update;
- capacidade local converge sem incremento duplicado;
- reabertura cria novo ciclo e preserva o histórico anterior;
- ciclo queued sem dispatch classificado pelo dry-run.

### V-05 — Elegibilidade/ausência

- heartbeat sem mudança material mantém revisão;
- alteração de away/out-of-office incrementa revisão e veta;
- mudança só de frescor não rejeita candidato;
- falha HubSpot no veto final continua fail-closed para o item;
- regras de horário local JUDAH continuam autoritativas.

### V-06 — Locks e Celery

- compare-delete aceita apenas owner token;
- liberação normal imediata;
- TTL recupera crash;
- retry com backoff/jitter só para exceções permitidas;
- erro permanente não reexecuta lote inteiro;
- task redelivered não duplica efeitos.

### V-07 — Gates universais

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy apps common core
uv run pytest -q
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
git diff --check
```

Testes nunca apontarão para banco não local. Usar o runner seguro e containers
descartáveis documentados pelo projeto.

## 6. Critérios de aceitação

- Um item inválido não impede a atribuição de um item válido posterior.
- Nenhum drain seleciona o mesmo ID duas vezes.
- Toda linha pronta muda de estado ou recebe defer explícito e temporizado.
- Métrica de atribuição nunca excede itens observados.
- Owner manual converge sem nova mutação HubSpot.
- Eventos repetidos e crashes não duplicam efeitos.
- Nenhum agente ausente, fora de horário ou sem capacidade recebe ticket.
- `queued_without_dispatch`, conflitos completed/fila e no-progress são
  visíveis e acionáveis.
- O plano de rollback foi exercitado em ambiente descartável.
- Runbook contém comandos exatos e stop conditions.

## 7. Rollout em produção

O projeto Railway não possui staging; portanto o rollout exige gates separados:

1. **R0 — pré-deploy read-only:** fila, cycles, attempts, migrations, locks,
   workers e flags; registrar baseline agregado.
2. **R1 — deploy de código:** API, worker e beat no mesmo commit; sem migration
   por padrão; health e Celery startup verdes.
3. **R2 — shadow observability:** ativar somente novos classificadores/métricas
   sem mudar owner; confirmar que outcomes fecham as contas.
4. **R3 — canário:** limitar agentes com mecanismo existente, processar pequeno
   lote controlado e confirmar owner real no HubSpot.
5. **R4 — enforcement:** liberar drain resiliente geral após aprovação explícita.
6. **R5 — reconciliação:** dry-run e autorização separada para ciclos/legado;
   nunca acoplar reparo de dados ao deploy.

Stop conditions:

- `assigned > total_pending`;
- repetição do mesmo queue row no drain;
- owner divergente;
- capacidade duplicada;
- aumento de `repair_required`/erros inesperados;
- migration/schema divergente;
- worker sem acesso ao banco/Redis/HubSpot.

## 8. Rollback

### Sem migration (caminho preferido)

- interromper enforcement novo e preservar ingestão/reconciliação;
- redeploy do último commit estável no Railway;
- não apagar fila nem tentativas automaticamente;
- isolar apenas itens comprovadamente problemáticos;
- executar reparador das tentativas vivas;
- confirmar owner real antes de qualquer replay.

Se a proteção exigir `AUTO_ASSIGNMENT_ENABLED=false`, usar apenas como
contenção sistêmica temporária; `may_ingest_queue` e `may_reconcile_queue`
continuam ativos. Um dado inválido isolado nunca justifica desligar o sistema.

### Com migration expansiva eventual

- manter colunas/tabelas adicionadas durante rollback de código;
- não executar reverse destrutivo em produção;
- desligar somente leitura/escrita da nova estrutura;
- reverter migration apenas em ambiente descartável para provar compatibilidade.

### Recuperação pós-rollback

- verificar fila, claims expirados, tentativas live/external_applied e owners;
- drain somente após readiness e autoridade confirmadas;
- registrar reconciliações e preservar histórico.

## 9. Arquivos previstos / watch list

Principais:

- `apps/support/matchmaker_service.py`
- `apps/support/durable_assignment_service.py`
- `apps/support/tasks.py`
- `apps/support/sat_service.py`
- `apps/support/owned_cache_lock.py`
- `apps/support/assignment_readiness.py`
- serviço de reconciliação em `apps/support/`
- testes focados em `apps/support/tests/`
- `docs/operations/absence-safe-assignment.md`

Possíveis, somente se o contrato exigir:

- `apps/support/auto_assign_service.py`
- `apps/webhooks/handlers/hubspot_handler.py`
- `apps/support/models.py` e nova migration expansiva
- `core/settings/base.py`

## 10. Fora de escopo

- alterar HMAC dos webhooks;
- substituir Celery/Redis/PostgreSQL;
- desligar agentes globalmente;
- inventar timestamps/ciclos para legado;
- executar backfill, deploy, flags ou DB write em produção nesta fase;
- corrigir toda projeção histórica antes de restaurar a resiliência do drain.

## 11. Stop point

Este documento encerra a fase PLAN. Implementação começa somente após Felipe
aprovar explicitamente este `master-plan.md`. Deploy, canário, reconciliação e
qualquer mutação de produção continuam sendo aprovações separadas.

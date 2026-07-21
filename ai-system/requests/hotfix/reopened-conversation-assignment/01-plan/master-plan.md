# Plano de implementação — ciclos de atendimento para conversas reabertas

**Request:** `hotfix/reopened-conversation-assignment`
**Data:** 21 de julho de 2026
**Ciclo/Fase:** F / PLAN
**Base:** `00-context/research.md`
**Implementação:** não iniciada
**Mutações em produção autorizadas:** nenhuma

## 1. Decisão

Implementar a abordagem recomendada no research: uma entidade explícita e
imutável de **ciclo de atendimento** no domínio `support`. O ticket HubSpot
continua sendo a identidade externa do caso, mas cada entrada comprovada no
estágio NOVO identifica um atendimento independente.

O hotfix não apagará, reciclará nem sobrescreverá tentativas ou fechamentos
anteriores. A idempotência deixa de significar "uma atribuição por ticket para
sempre" e passa a significar "um efeito por ocorrência e por ciclo".

A entrega seguirá **expand/migrate/contract**, em marcos compatíveis. Assim é
possível auditar ambiguidades antes de endurecer constraints e manter a
atribuição atual durante a expansão. Este plano não autoriza deploy, backfill em
base compartilhada, flags ou reparo dos tickets do incidente.

## 2. Invariantes de negócio

1. Um ticket possui vários ciclos históricos, mas no máximo um ciclo ativo.
2. Uma ocorrência confirmada de entrada em NOVO abre ciclo somente quando o
   anterior está terminal.
3. Reentrega, retry e sync da mesma ocorrência retornam o mesmo ciclo sem repetir
   atribuição, capacidade, log ou métrica.
4. Reatribuições dentro do mesmo atendimento permanecem no mesmo ciclo.
5. Evento antigo ou fora de ordem nunca altera o ciclo ativo mais novo.
6. Existe no máximo uma tentativa viva e uma atribuição automática concluída por
   ciclo.
7. Cada ciclo fechado tem exatamente um histórico, inclusive sem atribuição.
8. HubSpot é autoritativo para estágio e owner; JUDAH é autoritativo para a
   identidade e o estado operacional do ciclo após validar a ocorrência.
9. Timestamp ausente/não comprovável falha fechado: recuperar, adiar ou
   quarentenar; nunca usar `timezone.now()` como identidade.
10. A mutação de owner continua fora de transação longa. O protocolo
    `reserve -> apply -> finalize/compensate/repair` permanece a saga canônica.
11. Falha de um item do reparador não bloqueia o lote nem fica invisível.
12. Dado legado ambíguo não será associado por suposição.

## 3. Contrato técnico

### 3.1 Identidade do ciclo

Adicionar `SupportConversationCycle`, com UUID interno, `cycle_key` determinística
e chave natural:

```text
(source_system, source_account_id, hubspot_ticket_id, entered_stage_at)
```

- `source_system`: inicialmente `hubspot`;
- `source_account_id`: portal HubSpot configurado explicitamente;
- `entered_stage_at`: instante UTC confirmado de
  `hs_v2_date_entered_<NOVO_STAGE_ID>`;
- `source_event_id`: auditoria da entrega, sem participar sozinho da identidade.

Adicionar `HUBSPOT_PORTAL_ID` como configuração não secreta obrigatória para o
writer autoritativo. Não assumir silenciosamente single-portal. Config ausente
impede abertura de ciclo em produção e gera erro operacional, sem impedir leitura.

`cycle_key` deve ser versionada, determinística e segura para log. Não usar hora
de recebimento, UUID aleatório, owner, `eventId` isolado ou somente `ticket_id`.

### 3.2 Estados e transições

Estados: `queued`, `assigned`, `repair_required`, `closed`, `cancelled`.

```text
queued -> assigned -> closed
queued -> closed
queued|assigned -> repair_required
repair_required -> queued|assigned|closed|cancelled (reconciliação explícita)
queued -> cancelled
```

Estado terminal não volta a ativo; reabertura cria ciclo. O
`ConversationInstance` de `ai_agents` continua agregado da vida do ticket, não a
identidade do atendimento.

### 3.3 Constraints e projeções

O PostgreSQL será a última barreira:

- `cycle_key` e chave natural únicas;
- índice único parcial por conta + ticket nos estados ativos;
- um `NewConversation`, `AssignedConversation` e `ClosedConversation` por ciclo;
- uma tentativa viva por `cycle_id`;
- uma tentativa automática concluída por `cycle_id`;
- um `AssignmentLog` por tentativa;
- índices por ticket/abertura, estado/abertura e FKs de ciclo.

`NewConversation` e `AssignedConversation` são projeções ativas. Fechamentos,
tentativas, logs e reatribuições são históricos multi-ciclo. Unicidades globais
por ticket só saem após backfill e troca de todos os writers.

### 3.4 Publicação assíncrona

Usar `transaction.on_commit()` para trabalho dependente da criação do ciclo. O
sync periódico de NOVO permanece safety net para "commit feito, publish falhou"
e ganha telemetria de ciclo não despachado. Outbox transacional completo fica
fora desta entrega; reavaliar se a medição mostrar perda material de SLA.

## 4. Ordem e stop gates

```text
Gate A: contrato e perfil seguro dos dados
  -> Gate B: expansão de schema e dual-write
    -> Gate C: ingestão e protocolo durável por ciclo
      -> Gate D: fechamento, reatribuição, reparo e consumidores
        -> Gate E: backfill e constraints por ciclo
          -> Gate F: regressão PostgreSQL e prontidão
            -> Gate G: rollout (aprovação separada)
```

Falha em um gate bloqueia os seguintes. Gate G não decorre automaticamente de
testes verdes.

## 5. Work breakdown

### Gate A — contrato e perfil dos dados

#### BE-01 — Serviço de domínio do ciclo

Criar serviço tipado para:

- normalizar timestamp HubSpot em UTC e construir a chave versionada;
- classificar `created`, `duplicate`, `stale`, `active_conflict`,
  `identity_unavailable` e `repair_required`;
- centralizar abertura, lookup e transição sob `transaction.atomic()` e
  `select_for_update()`;
- impedir `get_or_create(ticket_id)` direto nos entrypoints.

Ao capturar `IntegrityError` de corrida, reler a chave natural e retornar o
resultado idempotente, sem repetir efeito externo.

**Alvos:** `apps/support/conversation_cycle_service.py`, `models.py` e
`tests/test_conversation_cycles.py`.

**Aceite:** transições cobertas; mesma ocorrência gera mesma identidade;
reentrada com ciclo ativo é conflito auditável, não fechamento implícito.

#### DB-01 — Profiling read-only

Criar comando que conte, sem PII:

- tickets simultaneamente em fila, atribuídos e fechados;
- múltiplos logs/tentativas e correlação por timestamps;
- tentativas vivas, `external_applied` e `repair_required`;
- linhas sem timestamp comprovável;
- divergência owner externo x local apenas com autorização separada.

Salvar resultado autorizado em `00-context/legacy-cycle-profile.md`. Testes usam
fixtures; banco não local exige pré-aprovação.

**Stop gate A:** confirmar `HUBSPOT_PORTAL_ID`, política para novo NOVO com ciclo
ativo, retenção de tentativas e tratamento do legado. Sem isso, nenhum backfill
compartilhado ou migration de contrato avança.

### Gate B — expansão e dual-write

#### DB-02 — Migration expansiva reversível

Criar migration sucessora de `support.0019`, sem reescrever histórico:

- tabela `support_conversation_cycles`;
- FKs nulas `cycle_id` em fila, atribuído, fechado, tentativa, log e reatribuição;
- constraints naturais, índice parcial e índices documentados;
- extensão do trigger de isolamento de writer.

Manter unicidades antigas e FKs nulas para compatibilidade de rolling deploy. O
reverse remove somente objetos adicionados. Se o volume exigir índice
concorrente, separar estado/banco em migration não atômica e testar esse caminho.

**Alvos:** `models.py`, novas migrations,
`test_conversation_cycle_migrations.py` e `test_runtime_guard_migration.py`.

#### BE-02 — Dual-write e readiness

Com `CONVERSATION_CYCLES_ENFORCED=false`:

- writers novos preenchem ciclo quando a ocorrência é comprovável;
- readers toleram legado nulo;
- comportamento de reabertura permanece legado nesta fase;
- divergência ciclo/projeção falha fechado e gera telemetria.

Readiness expõe somente contagens seguras: portal configurado, cobertura de FK,
ambiguidades, writers legados e versão mínima dos workers.

**Stop gate B:** apply/reverse/reapply em PostgreSQL 16; app antiga/nova lê o
schema; writer não autoritativo é rejeitado; comportamento produtivo não mudou.

### Gate C — ingestão e saga por ciclo

#### INT-01 — Preservar ocorrência HubSpot ponta a ponta

- devolver `entered_novo_at`/`entered_closed_at` já solicitados por
  `get_ticket_details()`;
- propagar `source_event_id` do `WebhookEvent` pelo handler e task;
- resolver ausência por payload, propriedade atual confirmada e histórico;
- se ainda ausente, adiar/quarentenar;
- remover `or timezone.now()` dos entrypoints de NOVO;
- validar pipeline, estágio e ausência de owner antes da abertura;
- manter `support` independente do `ConversationEvent` de `ai_agents`.

Não tornar `WebhookEvent.event_id` globalmente único: há outras fontes e IDs
vazios. A chave do ciclo dá idempotência durável; o evento fica para auditoria.

**Alvos:** `apps/integrations/hubspot/client.py`, handler HubSpot, tasks,
`matchmaker_service.py`, `auto_assign_service.py` e testes de integração.

#### BE-03 — Fila e reserva cycle-aware

- admitir via `open_or_get_cycle()`;
- enfileirar por ciclo e publicar com `on_commit()`;
- reserva automática/manual recebe ou deriva e trava o ciclo ativo;
- veto de tentativa fica dentro da transação e usa ciclo no single/drain;
- preservar FIFO e `FOR UPDATE SKIP LOCKED`;
- incluir ciclo no idempotency key, snapshot, logs e resultados internos;
- abortar antes do HubSpot se o ciclo não estiver mais `queued`.

#### BE-04 — Finalize, compensate e reconcile

- finalizar somente projeção/tentativa do ciclo e transicionar para `assigned`;
- compensar capacidade e fila somente daquele ciclo;
- reconciliar owner externo contra tentativa e ciclo ativo;
- retry nunca migra tentativa para um ciclo posterior;
- tentativa antiga retorna `skipped_stale_cycle`;
- preservar SAT e veto final de ausência já existentes.

**Alvos BE-03/04:** `durable_assignment_service.py`, `matchmaker_service.py`,
`tasks.py`, `queue_service.py` e testes duráveis/SAT/Matchmaker.

**Stop gate C:** não há owner mutation sem reserva; webhook, sync e drain
convergem; crash após `external_applied` repara o ciclo original; ausência segura
continua verde.

### Gate D — fechamento, reatribuição, reparo e consumidores

#### BE-05 — Fechar por ciclo

- localizar e travar ciclo ativo compatível;
- exigir `entered_closed_at >= entered_stage_at` e confirmar estágio em dúvida;
- duplicata do mesmo fechamento é no-op; fechamento antigo é stale;
- criar `ClosedConversation` por ciclo, inclusive sem atribuição;
- decrementar capacidade uma vez e transicionar ciclo/projeções atomicamente;
- remover `ClosedConversation.get_or_create(ticket_id)`.

O lifecycle de AI continua best-effort por ticket; falha dele não desfaz o
fechamento de suporte. Logs correlacionam ticket, ciclo e evento.

#### BE-06 — Owner changes e admin por ciclo

- associar `task_handle_owner_change()` e `ConversationReassignment` ao ciclo;
- ignorar webhook de owner antigo que não corresponde ao ciclo atual;
- manual assign/force reassign travam ciclo e retornam `cycle_id` aditivamente;
- operações admin usam protocolo durável ou saga equivalente com idempotency key,
  eliminando HubSpot-first sem registro recuperável;
- APIs mantêm `hubspot_ticket_id` para compatibilidade.

**Alvos:** `auto_assign_service.py`, `tasks.py`, `admin_api.py`, `api.py`,
`schemas.py` e testes de lifecycle/admin/API.

#### BE-07 — Reparador isolado por item

- lote limitado/determinístico e claim que evite reparo concorrente;
- um `atomic()`/savepoint por tentativa;
- classificar conflito esperado, stale e exceção inesperada;
- persistir erro/estado antes de continuar;
- contar `completed`, `retryable`, `repair_required`, `conflict`,
  `failed_unexpected` e `skipped_stale_cycle`;
- alerta agregado sem esconder stack trace;
- não escolher ciclo para legado `external_applied` ambíguo.

#### DATA-01 — Métricas e retenção

- contar atendimentos por ciclo, não ticket distinto;
- fechamento diário consulta `ClosedConversation`, não
  `AssignedConversation.closed_at` após remoção da projeção;
- tempos e dashboards agrupam por ciclo;
- logs mostram ticket + ciclo para distinguir reabertura de reatribuição;
- definir retenção antes de preservar a purga fixa de 30 dias; preferir política
  alinhada à auditoria ou arquivamento.

**Alvos:** serviço durável, tasks, queue service, APIs/schemas, comando de health
e testes de métricas/retenção.

**Stop gate D:** dois fechamentos preservados; reatribuição não abre ciclo; item
venenoso não bloqueia lote; APIs compatíveis e métricas cycle-aware.

### Gate E — backfill e contrato

#### DB-03 — Backfill idempotente/reiniciável

Criar management command com `--dry-run`, cursor/checkpoint, limite, filtro por
ticket e relatório. Evitar migration de dados longa.

Correlação em ordem:

1. fila/atribuído + `entered_queue_at` comprovado;
2. fechado + entrada/fechamento;
3. tentativa vinculada à fila, log vinculado à tentativa e janelas coerentes;
4. reatribuições dentro do intervalo;
5. evidência HubSpot, somente quando autorizada.

Para legado sem ocorrência comprovável, usar identidade determinística marcada
`identity_source=legacy_backfill`, baseada em IDs persistidos, sem inventar
timestamp. Ambiguidade vai para relatório/quarentena.

O comando é reexecutável, não chama HubSpot por padrão e não altera owner. Os
tickets do incidente têm aprovação e procedimento separados.

#### DB-04 — Migration de contrato

Depois de cobertura completa ou exceções isoladas:

- remover unicidades globais incompatíveis;
- ativar constraints por ciclo e validar FKs;
- manter FKs nulas durante versão mista, bloqueando writers novos sem ciclo;
- tornar obrigatório em release posterior após zero nulos/writers antigos.

Rollback preserva schema/ciclos. Não recriar unicidade global após existir mais
de um ciclo. Reversão segura é funcional, não destrutiva.

**Stop gate E:** dry-run, reexecução idêntica, contagens conciliadas, ambiguidade
quarentenada e relatório revisado antes de execução compartilhada.

### Gate F — testes e regressão

#### V-01 — Domínio/idempotência

- ciclo 1: entrada, retries, atribuição e fechamento únicos;
- reentrada cria ciclo 2; segundo fechamento preserva ambos;
- três ou mais reentradas;
- reatribuição permanece no ciclo;
- timestamp ausente/malformado não usa relógio local;
- ciclo ativo conflitante e eventos stale seguem política.

#### V-02 — Concorrência PostgreSQL 16

- dois workers, uma ocorrência: um ciclo/fila/reserva;
- webhook + sync convergem;
- single + drain têm a mesma invariância;
- ocorrências distintas não deixam dois ciclos ativos;
- fechamento/reabertura concorrentes serializam;
- owner change antigo não altera ciclo novo;
- exercitar locks, `SKIP LOCKED`, índice parcial e trigger;
- repetir cenários para detectar flakiness.

#### V-03 — Falhas distribuídas

- crash antes do HubSpot não muda owner;
- crash depois do HubSpot e antes do finalize converge;
- retry/compensação não duplica capacidade/log/métrica;
- resposta ambígua + owner esperado faz forward recovery;
- owner divergente vira `repair_required`;
- tentativa velha não finaliza ciclo novo;
- conflito de um item não para reparador; inesperado alerta e persiste contexto.

#### V-04 — Migration/backfill/compatibilidade

- expand apply/reverse/reapply a partir de `support.0019`;
- fixtures pending, assigned, closed, completed, external_applied e reaberto;
- dry-run, interrupção e reexecução do backfill;
- contrato recusa dois ativos e aceita múltiplos fechados;
- rollback não perde ciclos/recria constraint impossível;
- `makemigrations --check --dry-run` limpo.

#### V-05 — Regressão por serviço

- webhooks: HMAC intocado, NOVO/FECHADO e source event;
- HubSpot: propriedades, erros tipados, backoff/circuit breaker;
- Celery: retry/redelivery, Beat e payload antigo durante rollout;
- Matchmaker/SAT: FIFO, capacidade, ausência e veto final;
- admin/API: manual, forced e schemas aditivos;
- AI lifecycle: terminal -> `QUEUE_PENDING` sem virar ciclo;
- métricas e writer/environment guards;
- suites de support, webhooks, ai_agents e integração HubSpot.

#### V-06 — Quality gates

Em PostgreSQL 16 + Redis 7 descartáveis, nunca base compartilhada:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy apps common core
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
uv run pytest apps/support/tests apps/webhooks/tests apps/ai_agents/tests
uv run pytest
git diff --check
```

Registrar evidência em `03-verification/` e preencher `HANDOFF.md` antes de
VERIFY. SQLite é lane rápida, não prova de release.

**Stop gate F:** suíte completa e gates verdes, migrations PostgreSQL provadas,
critérios cobertos, docs atualizados e sem TODO/FIXME/print novo.

### Gate G — rollout com aprovação separada

#### OPS-01 — Expand/migrate/contract

1. Deploy aditivo + dual-write com enforcement desligado.
2. Verificar API/Worker/Beat, readiness e ausência de writer legado.
3. Backfill em staging/clone: dry-run, execução, reconciliação e revisão.
4. Deploy cycle-aware + constraints; drenar workers antigos.
5. Canário sem desligar globalmente a atribuição; sempre com saga e ausência.
6. Observar reentrada, duplicatas, fila, `external_applied`, conflitos e métricas.
7. Nova aprovação para enforcement geral.
8. Contract tardio de NOT NULL/compatibilidade após janela estável.

Não copiar automaticamente rollout assignment-off antigo: este hotfix corrige a
atribuição. Kill switch fica disponível somente para contenção.

#### OPS-02 — Observabilidade

Logs: `ticket_id`, `cycle_id`, chave segura, `source_event_id`, `attempt_id`,
estado anterior/novo e classificação.

Métricas/alertas:

- ciclos abertos, reabertos, atribuídos, fechados, cancelados e em conflito;
- duplicatas idempotentes;
- mais de um ciclo ativo por ticket (SLO zero);
- ciclo sem dispatch acima do SLA;
- idade de `external_applied`/`repair_required`;
- falhas por item/lote parcial;
- divergência de owner e linhas sem ciclo;
- writer legado detectado.

#### OPS-03 — Runbook e rollback

Atualizar `docs/operations/absence-safe-assignment.md` ou criar runbook com
diagnóstico, consultas read-only, backfill, ambiguidades, canário e rollback.

Rollback seguro: desligar enforcement (ou assignment em incidente de
integridade), manter ingestão/reconciliação e dados, impedir novos efeitos,
reconciliar tentativas externas, nunca reverter destrutivamente e exigir
aprovação para mutação manual em HubSpot/produção.

## 6. Impacto em outros serviços

| Componente | Impacto | Compatibilidade |
|---|---|---|
| HubSpot webhooks | Propaga ocorrência/evento; timestamp fail-closed | HMAC e `202` inalterados |
| HubSpot client | Expõe timestamps e eventual histórico | Erros/circuit breaker preservados |
| Celery Worker | Payload cycle-aware; repair isolado | Aceitar tarefas antigas na janela |
| Celery Beat | Recupera ciclo não despachado | Não duplicar efeitos |
| Matchmaker/SAT | Reserva por ciclo | FIFO, presença e veto preservados |
| PostgreSQL | Entidade, FKs, índices, backfill | Prova obrigatória em PG16 |
| Redis | Locks incluem ciclo/token | Nunca autoridade de idempotência |
| Admin/API | `cycle_id` aditivo e ciclo ativo | `ticket_id` permanece |
| AI lifecycle | Continua por ticket | Sem acoplamento transacional |
| Métricas | Unidade vira ciclo | Documentar data de corte |
| Railway/readiness | Portal, cobertura e writers | Sem valores secretos em logs |

## 7. Arquivos previstos

**Novos:** serviço de ciclo; migrations após `0019`; comando de backfill; testes
de domínio, migration e backfill; runbook se necessário.

**Modificados:** `models.py`, serviço durável, Matchmaker, auto assign, tasks,
queue service, admin/API/schemas, comandos operacionais, HubSpot client, webhook
handler, settings/readiness, docs e testes afetados.

Esta é uma watch list, não autorização para editar tudo. Expansão de escopo deve
ser registrada no `STATUS.md`.

## 8. Critérios finais

- [ ] Retry da mesma ocorrência é no-op.
- [ ] Reentrada legítima recebe nova atribuição.
- [ ] Múltiplos ciclos preservam agentes, tempos e logs.
- [ ] Um ciclo ativo/tentativa viva por chave.
- [ ] Evento stale não altera ciclo corrente.
- [ ] Timestamp ausente nunca usa relógio local.
- [ ] Saga converge nas fronteiras de crash.
- [ ] Reparador isola item e expõe resultado parcial.
- [ ] Admin/owner changes carregam ciclo correto.
- [ ] Métricas contam ciclos e fechamentos corretos.
- [ ] Backfill é dry-run, idempotente e auditável.
- [ ] Expand/reverse/contract provados em PostgreSQL 16.
- [ ] APIs retrocompatíveis de forma aditiva.
- [ ] SAT, ausência, guards e rollout gate sem regressão.
- [ ] Full suite, Ruff, mypy, Django e diff check verdes.
- [ ] Produção permanece atrás de aprovação explícita.

## 9. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| NOVO não muda em alguma reentrada | validar HubSpot antes do enforcement; fail-closed |
| FECHADO antigo após reabertura | comparar ocorrência e ciclo sob lock |
| Writers antigos/novos misturados | schema aditivo, readiness e drain antes de ligar |
| Backfill incorreto | evidência determinística, dry-run e quarentena |
| Índice bloqueia tabela grande | medir; índice concorrente/validação posterior |
| HubSpot aplicado e DB falha | saga + repair por ciclo |
| Métrica muda historicamente | versionar semântica e data de corte |
| Retenção apaga evidência | decidir política antes da purga |
| Rollback recria unicidade impossível | rollback funcional, não destrutivo |

## 10. Aprovações obrigatórias

Felipe deve aprovar separadamente:

1. este plano e as regras de identidade/estado;
2. `HUBSPOT_PORTAL_ID`, ciclo ativo conflitante e retenção;
3. profiling em base não local ou leitura externa em lote;
4. backfill em staging/produção;
5. tratamento dos tickets `46934213935` e `46889914778`;
6. deploy de cada marco;
7. canário e enforcement geral;
8. reparo manual ou mutação em produção/HubSpot.

## 11. Próxima ação

Após aprovação, iniciar somente o **Gate A**, registrar a transição no
`STATUS.md`, produzir perfil/decisões e parar novamente antes de migration,
backfill ou mutação compartilhada.

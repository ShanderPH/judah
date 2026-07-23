# Research — resiliência da fila de atribuição

**Request:** `hotfix/assignment-queue-resilience`
**Branch:** `hotfix/assignment-queue-resilience`
**Data:** 23 de julho de 2026
**Escopo:** análise e planejamento; nenhuma implementação neste artefato

## 1. Objetivo

Garantir que a fila de atendimento continue progredindo quando uma conversa
individual contiver estado legado, identidade incompleta, owner externo,
tentativa anterior, ciclo obsoleto ou outra inconformidade. Uma falha local deve
ser convergida, deferida ou isolada; nunca pode impedir conversas independentes.

## 2. Estado de produção confirmado antes do planejamento

- A fila operacional foi limpa por autorização explícita: 19 linhas removidas
  de `new_conversations`, sem apagar tentativas, logs, ciclos ou históricos.
- O drain seguinte confirmou `total_pending=0`, `assigned=0`, `remaining=0`.
- Autoatribuição, banco, cache e writer autoritativo permaneceram ativos.
- Permaneceram 17 ciclos `queued` sem dispatch. Eles não estão mais na fila,
  mas exigem reconciliação owner/ciclo antes de qualquer enforcement.
- Antes da limpeza, uma linha legada sem `cycle_id` possuía tentativa
  `completed`; o drain repetia essa mesma linha, reportava mais atribuições do
  que itens e não reduzia a fila.

## 3. Cadeia funcional rastreada

```text
HubSpot webhook de NOVO
  -> apps/webhooks/handlers/hubspot_handler.py
  -> transaction.on_commit(task_matchmaker_assign_single.delay)
  -> task_matchmaker_assign_single
  -> SAT force_refresh
  -> enqueue_new_ticket / open_or_get_cycle
  -> matchmaker_assign_next
  -> reserve_next_assignment
  -> HubSpot owner update
  -> finalize / compensate / repair
  -> AssignedConversation + AssignmentLog + capacidade + ciclo

Safety nets:
  Celery Beat -> matchmaker drain a cada 60s
  SAT -> drain quando agente se torna elegível
  sync NOVO -> reconstrução diária da fila
  repair task -> convergência de tentativas ambíguas a cada 60s

Owner externo/manual:
  HubSpot owner webhook
  -> task_handle_owner_change
  -> _do_handle_owner_change
  -> hoje só converge se AssignedConversation já existir
```

## 4. Defeitos e riscos confirmados na codebase

### 4.1 Head-of-line por tentativa concluída

`reserve_next_assignment()` procura tentativa `completed` pelo escopo do ciclo
ou, para legado, apenas por `ticket_id`. Ao encontrá-la, retorna
`Reservation(completed, "completed")`. O Matchmaker converte isso em
`AssignmentOutcome.ASSIGNED`, mas a linha residual não é removida, deferida nem
quarentenada.

### 4.2 Drain sem prova de progresso

`matchmaker_drain_queue()` repete até `total_pending + 5`, mas não acompanha o
ID selecionado, não valida redução da fila e incrementa `assigned` para no-op.
O mesmo item pode consumir todo o lote e produzir métricas impossíveis.

### 4.3 Escopo legado incompatível com reabertura

Para `cycle_id is null`, tentativa e idempotency key usam o ticket inteiro.
Uma atribuição histórica pode ser confundida com o atendimento atual. Isso é
incompatível com múltiplas entradas no estágio NOVO.

### 4.4 Falhas isoláveis interrompem o lote

Alguns resultados retornam sem transicionar o item; outros encerram o drain no
primeiro defer ou conflito. Não há contrato único que obrigue todo resultado a
ser `assigned`, `converged`, `quarantined`, `deferred` ou `skipped` com motivo.

### 4.5 Atribuição manual não converge fila pendente

`task_handle_owner_change()` ignora owner inicial quando `previousValue` está
ausente. `_do_handle_owner_change()` retorna como ciclo stale se ainda não há
`AssignedConversation`. Assim, owner manual no HubSpot pode coexistir com fila
e ciclo locais ainda ativos.

### 4.6 Revisão material e heartbeat estão acoplados

O SAT pode atualizar `availability_revision` em heartbeats sem alteração
material. O Matchmaker rejeita o candidato se a revisão mudou entre leitura
remota e lock, mesmo quando o estado elegível permaneceu equivalente.

### 4.7 Locks Redis dependem do TTL no caminho normal

`OwnedCacheLock` procura uma interface que não está exposta diretamente pelo
backend Redis nativo do Django. Produção registra
`owned_cache_lock_release_deferred_to_ttl`; por até 60/120 segundos, retries
legítimos podem ser suprimidos. O lock Redis está funcionando como requisito de
correção, embora o banco já possua locks e constraints duráveis.

### 4.8 Retry Celery amplo demais

Tasks capturam `Exception` e repetem sem taxonomia consistente. Erro permanente
de dado, conflito já convergido, indisponibilidade do provedor e falha sistêmica
podem receber o mesmo tratamento.

### 4.9 Readiness detecta divergência, mas não impede starvation

Há contagens de legado e `queued_without_dispatch`, porém não existem sinais
para item venenoso na cabeça, drain sem progresso, `assigned > total_pending`,
idade do item pronto ou repetição do mesmo ID.

## 5. Princípios técnicos atuais aplicáveis

- Django 5.2: usar `transaction.atomic()` curto, savepoint por item,
  `select_for_update(skip_locked=True)` para consumidores concorrentes e
  `transaction.on_commit()` somente para efeitos dependentes de commit.
- Celery 5: tasks idempotentes; retry apenas para exceções classificadas;
  backoff exponencial limitado e jitter; erro de item deve virar estado durável,
  não loop ilimitado da task.
- PostgreSQL/Supabase: constraints como última barreira; inspecionar locks e
  blocking; migrations via caminho privilegiado; runtime comum sem DDL;
  rollout expansivo e rollback funcional não destrutivo.
- Python 3.14: resultados tipados (`StrEnum`/dataclass), exceções específicas,
  contadores estruturados e stack trace preservado para falha inesperada.
- Falha local e falha sistêmica não são equivalentes: dado inválido é isolado;
  perda do banco, autenticação HubSpot inválida ou outage generalizado preserva
  a fila, abre circuito e impede efeitos externos inseguros.

## 6. Documentação primária consultada

- Django 5.2 — transactions/savepoints: <https://docs.djangoproject.com/en/5.2/topics/db/transactions/>
- Django 5.2 — `select_for_update`: <https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update>
- Celery stable — tasks/retries: <https://docs.celeryq.dev/en/stable/userguide/tasks.html>
- Supabase — database migrations: <https://supabase.com/docs/guides/deployment/database-migrations>
- Supabase — database inspection/locks: <https://supabase.com/docs/guides/database/postgres/data-deletion>

## 7. Decisão de ciclo

O incidente começa como Manutenção/P0, mas a correção toca mais de cinco
arquivos e altera invariantes entre fila, protocolo durável, Celery, SAT,
reconciliação manual e observabilidade. Conforme `AGENTS.md`, a request é
promovida para Ciclo F e exige aprovação do plano antes da implementação.

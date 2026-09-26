# Rollout operacional — pendente

Pré-condições: suíte e concorrência PostgreSQL aprovadas, decisão histórica resolvida, PR revisado, SHA único para API/Worker/Beat, sem migrations e sem alteração de flags.

## R0 — baseline

Medir em consulta autorizada e somente leitura: assigned × occupancy, ciclos assigned × occupancy, close occurrences × ClosedConversation e close occurrences × transições CLOSED. Registrar agregados em `03-verification/pre-repair-baseline.md`.

## Live fix

Deploy normal do mesmo SHA em `judah`, `judah-worker` e `judah-beat`. Smoke controlado: assignment → close → owner removal. Conferir ciclo, projeções, lifecycle e capacidade. Observar retries, erros/Sentry e taxa de novas divergências antes de reparar o histórico.

## Repair

Após autorização operacional para provider reads:

```bash
python manage.py reconcile_ticket_closures --limit 100
```

Interromper se houver classe ampla de ambiguidade. Após aprovação explícita de canary:

```bash
python manage.py reconcile_ticket_closures --limit 5 --apply
```

Conferir DB, provider e capacidade após cada lote. `--offset N` pagina o ledger em ordem estável de criação/id; guardar offsets executados e recomeçar lotes interrompidos, pois o serviço é idempotente. Não executar automaticamente nem usar bulk SQL.

## Observabilidade

Agregação dos logs `ticket_close_occurrence` por `classification`, e `webhook_event_stale_occurrence_revalidated` para reprocessamento stale. Gates: `reopen_not_materialized`, `identity_unavailable`, `conflict`, residual assigned por ciclo fechado e close sem projeção/lifecycle. Critério inicial: nenhuma nova divergência após a janela operacional acordada; backlog histórico não precisa chegar imediatamente a zero.

## Rollback

Reverter o commit/PR e redeployar API/Worker/Beat no mesmo SHA anterior. Parar repair batches. Não desfazer fechamentos comprovados e não reverter dados por SQL destrutivo.

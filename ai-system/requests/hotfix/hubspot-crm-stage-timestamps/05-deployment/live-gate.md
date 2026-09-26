# Deploy e gate live

1. Revisar e integrar o PR; registrar SHA e horário UTC do deploy em API, worker e beat.
2. Não executar `reconcile_ticket_closures --apply` nem repair histórico.
3. Após deploy, acompanhar uma **nova ocorrência real** no log `ticket_close_occurrence`: `classification=applied_current` e `domain_applied=true` para o mesmo `source_event_id`/ciclo. Confirmar por leitura que o ciclo está `closed`, existe `ClosedConversation`, não existe `AssignedConversation` ativa para esse ciclo e occupancy está `closed`.
4. Executar a consulta read-only em `ai-system/requests/hotfix/live-close-convergence/03-verification/live-close-cohorts.sql` com o corte do deploy. Critério: `new_code_divergent_cycles=0` na janela operacional. Relatar backlog anterior separadamente.
5. Se qualquer um dos sinais falhar, manter o hotfix aberto e investigar os logs `ticket_close_projection_inconsistency`, `task_handle_ticket_closed_retry` e `ticket_close_occurrence`. Não interpretar `ConversationEvent.PROCESSED` como aplicação do domínio.

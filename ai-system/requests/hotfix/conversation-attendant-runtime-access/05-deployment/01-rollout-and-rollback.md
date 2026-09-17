# Rollout e rollback

## Gate antes de produção

1. Aplicar `support.0032_grant_conversation_attendant_runtime_access` em staging com a credencial de schema.
2. Confirmar `SELECT/INSERT/UPDATE=true` e `DELETE=false` para `judah_staging_runtime`.
3. Confirmar RLS habilitado e nenhum privilégio para `PUBLIC`, `anon` e `authenticated`.
4. Executar um `record_instance_attendant` idempotente com o runtime de staging e verificar create/update.

## Produção

Aplicar pela etapa `railway_predeploy`; não executar SQL manual. Confirmar a linha da migration nos logs e consultar
`has_table_privilege` após o deploy. Monitorar `matchmaker_attendant_history_failed`,
`task_handle_owner_change_retry` e `permission denied for table conversation_instance_attendants`.

## Rollback

Reverter para `support.0031_ticket_capacity`. O reverse revoga somente `SELECT, INSERT, UPDATE` dos papéis de runtime.
Como isso reintroduz a falha conhecida, rollback deve ocorrer apenas se o grant produzir um efeito inesperado e deve ser
acompanhado de bloqueio do fluxo ou mitigação operacional explícita.

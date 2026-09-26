# Rollout e prova em produção

1. Revisar e fazer merge da PR. Registrar SHA resultante e instante UTC do deploy.
2. Implantar o mesmo SHA em `judah`, `judah-worker` e `judah-beat`. Não executar `reconcile_ticket_closures --apply`.
3. Executar apenas leituras: readiness (`recent_close_projection_inconsistencies` e métrica `ticket_close_projection_inconsistencies_recent`) e a consulta do serviço com corte em `created_at >= deploy_at`.
4. Para a prova live, cruzar ciclos criados após o SHA com ocorrências de fechamento cujo `effective_at` seja posterior ao SHA. Contar apenas occupancy `closed`, ciclo `assigned`/`queued` e ausência de `ClosedConversation`. Aceite: zero durante janela operacional acordada.
5. Relatar backlog anterior separadamente. Correlacionar rejeições, retries e falhas finais da task pelos logs `ticket_close_occurrence`, `ticket_close_domain_mutation_rejected`, `task_handle_ticket_closed_retry` e `ticket_close_projection_inconsistency`.
6. Só após janela sem nova divergência: reparador histórico em dry-run, canary pequeno autorizado, validação DB/HubSpot/capacidade e lotes controlados.

`ConversationEvent.PROCESSED` não serve como evidência de fechamento aplicado. O outcome canônico exige `domain_applied=true` e confirmação das projeções.

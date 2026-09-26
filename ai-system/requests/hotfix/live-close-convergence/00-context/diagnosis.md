# Diagnóstico do fechamento live

## Caminho

O webhook grava `WebhookEvent`; `process_webhook_event` normaliza `ConversationEvent` e despacha `task_handle_ticket_closed` via `hubspot_handler`. O webhook marca ambos como processados após o dispatch. A task executa `handle_ticket_closed`, que cria `TicketCloseOccurrence`, resolve ciclo pelo horário, reconcilia provider e occupancy, e materializa ciclo, filas, `ClosedConversation`, lifecycle e capacidade.

## Causa confirmada no código

`owner_reconciliation_service.reconcile_ticket` era o único escritor de `SupportTicketOccupancy.state = closed` no fluxo de observação. Qualquer observação do provider em estágio FECHADO podia gravar `closed`. No modo `shadow`, a rotina nunca tentava fechar o ciclo. No modo `enforce`, só tentava se `entered_closed_at` existisse e ignorava o resultado de `_apply_ticket_closed`. Assim, uma observação sem horário válido ou uma classificação rejeitada confirmava occupancy `closed` com ciclo `assigned` e sem `ClosedConversation`.

O fluxo de ocorrência separava a transação da occupancy da transação de `apply_close_occurrence`. Uma falha entre elas podia confirmar apenas occupancy. Além disso, `_transition_lifecycle_best_effort` engolia exceções inesperadas; uma repetição posterior encontrava ciclo fechado e retornava `DUPLICATE`, sem completar lifecycle. `task_handle_ticket_closed` retornava normalmente sem writer authority, e `handle_ticket_closed` classificava a falta de authority como `CONFLICT`. Essas rotas geravam confirmação operacional falsa.

`ConversationEvent.PROCESSED` é persistido no processamento do webhook, depois do dispatch assíncrono. Não afirma que a task materializou o domínio. O teste de integração comprova essa semântica.

## Escritores auditados

- `owner_reconciliation_service.reconcile_ticket`: atribui `row.state` a partir do snapshot do provider e salva occupancy; chamado por webhook de owner, portfolio, readback, recheck e fechamento.
- `capacity_service.ticket_transaction`: cria occupancy em `unknown`; não a fecha.
- `legacy_cycle_backfill`: escreve estado `closed` de **ciclos**, não de occupancy.
- Outros serviços consultam occupancy ou mudam revisão/ciclo; não atribuem `state = closed`.

O diagnóstico identifica mecanismos reproduzíveis, não afirma qual sequência exata ocorreu nos três tickets de produção. Essa sequência requer correlação read-only de logs por `source_event_id` e ticket.

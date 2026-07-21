# Gate D - fechamento, owner/admin, reparo e metricas

## Implementado

- Fechamento resolve o ciclo ativo mais novo, rejeita evento anterior a
  `entered_stage_at`, grava um `ClosedConversation` por ciclo e transiciona o
  ciclo para `closed` junto da remocao da projecao ativa.
- A migration `0022_closed_conversation_multi_cycle` remove apenas a unicidade
  historica global de `ClosedConversation.hubspot_ticket_id`; a unicidade por
  ciclo adicionada no Gate B permanece.
- Owner changes travam a projecao atribuida e descartam eventos cujo owner
  anterior nao corresponde ao owner do ciclo corrente.
- Manual assign e force reassign retornam `cycle_id`. Force reassign persiste
  uma reserva de `ConversationReassignment` antes da mutacao externa e a
  finaliza apos o HubSpot confirmar.
- O reparador usa claim com `select_for_update(skip_locked=True)`, transacao por
  item, continua apos excecao e publica contagens separadas.
- Metricas diarias consultam `ClosedConversation`. A retencao usa
  `ASSIGNMENT_ATTEMPT_RETENTION_DAYS`, com fallback de 365 dias.

## Limites

- Linhas legadas sem ciclo continuam aceitas com enforcement desligado.
- Nenhum deploy, backfill, flag, HubSpot real ou banco compartilhado foi usado.

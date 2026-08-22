# Workflows operacionais

## Novo atendimento

1. HubSpot informa entrada no estágio NOVO por propriedade calculada.
2. JUDAH registra o evento e abre/reabre o ciclo idempotente.
3. O atendimento entra em `new_conversations`.
4. Matchmaker aplica calendário, disponibilidade, ausência e capacidade.
5. O owner é atualizado no HubSpot e a conversa passa para atribuída.

## Fechamento

1. HubSpot informa entrada no estágio FECHADO.
2. JUDAH converge instâncias do ticket para `CLOSED`.
3. O ciclo é fechado, capacidade e métricas são atualizadas pelos fluxos
   operacionais existentes.

## Mensagem

Uma mensagem recebida pode ser preservada no ledger, mas não chama bot. A futura
decisão de identificação e triagem será produzida pelo n8n em uma etapa posterior.

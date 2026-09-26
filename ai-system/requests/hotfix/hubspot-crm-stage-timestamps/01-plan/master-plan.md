# Plano do hotfix

## Escopo

1. Normalizar os horários de entrada nos estágios NOVO e FECHADO do `get_ticket_details()` e o horário NOVO da busca CRM para `datetime` UTC aware.
2. Fazer abertura de ciclo, decisão de reabertura, reconciliação de owner e fechamento interno consumir o `datetime` já normalizado. O webhook continua aceitando somente epoch-ms.
3. Reproduzir os dois horários reais em teste que percorre cliente CRM e fechamento live, incluindo a segunda entrega idempotente. Cobrir reabertura posterior e reconciliação por owner com `datetime`.
4. Executar testes focados, `ruff check`, `ruff format --check`, `mypy`, suíte local completa, migration check e `git diff --check`.

## Critérios de aceite

- Para a ocorrência real: `classification=applied_current`, `domain_applied=true`, ciclo `closed`, uma `ClosedConversation`, nenhuma `AssignedConversation` e occupancy `closed`.
- Reabertura posterior retorna `reopen_not_materialized`; retry retorna `duplicate` sem efeito adicional.
- Falha de provider ou lifecycle conserva as projeções anteriores por rollback; o parser de webhook continua rejeitando ISO-8601.
- Após deploy, observar um fechamento real aplicado e `new_code_divergent_cycles=0`. Testes locais não encerram o gate.

# Master plan

## Critérios de aceitação

- `404` ao atribuir um ticket coloca o item em quarentena auditável e o dreno continua.
- Falhas transitórias preservam o item, incrementam tentativas e aplicam backoff.
- Um item inválido na cabeça da fila não impede a atribuição do próximo item válido.
- `404` não abre o circuit breaker compartilhado do HubSpot.
- Um novo evento NOVO pode reabrir lifecycle `IGNORED`/`CLOSED` e limpa `closed_at`.
- Ruff, mypy e testes locais passam sem conexão a bases não locais.

## Tarefas

- BE-01: preservar status e retryability dos erros HubSpot.
- BE-02: adicionar quarentena/backoff à fila e migration.
- BE-03: tornar o dreno resiliente a poison messages.
- BE-04: corrigir reabertura de lifecycle.
- V-01: cobrir 404, transient error, circuit breaker e lifecycle em testes.

# V-01 — cenário vermelho da corrida de abertura

## Cenário

- Janela operacional abre às 09:00 em `America/Sao_Paulo`.
- Um item do backlog entrou antes da abertura.
- O agente A já está `eligible`; o agente B ainda está `stabilizing`.
- Ambos estão ativos, com identidade, auto-assign e capacidade.

## Limite histórico

Esta fixture prova a corrida sistêmica no caminho comum `reserve_next_assignment()`. Ela não afirma que este
foi o snapshot histórico exato do ticket HubSpot `48154078600`, pois esse conjunto completo não foi
recuperado na investigação.

## Comando vermelho

```powershell
uv run pytest apps/support/tests/test_opening_cohort_barrier.py -vv
```

## Falha esperada antes da implementação

O protocolo atual cria uma reserva/`AssignmentAttempt` para A. O contrato exige
`deferred_stabilizing_cohort`, sem attempt e sem consumo de capacidade. Portanto o teste deve falhar na
asserção do reason code, e não por import, fixture ou ambiente.

## Evidência observada

- Vermelho: `ReservationReason.RESERVED`, exatamente o consumo prematuro esperado.
- Verde: `deferred_stabilizing_cohort`, zero attempt e capacidade inalterada.

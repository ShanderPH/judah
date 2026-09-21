# Plano — finalizar coortes de abertura sem depender da fila

## Escopo

- BE-01: expor uma operação idempotente de finalização de coorte sob lock.
- BE-02: executar a finalização no callback depois do refresh SAT e antes do drain.
- BE-03: executar o fallback de deadline antes do retorno rápido por fila vazia.
- OBS-01: separar a coorte da janela atual das coortes ativas órfãs no readiness.
- V-01: reproduzir callback `shadow` com fila vazia e fallback Beat sem fila.
- V-02: cobrir readiness com resíduo histórico e coorte atual.
- V-03: executar testes de suporte, ruff e mypy relevantes.

## Critérios de aceitação

1. Callback fecha por `all_settled` mesmo quando a fila já foi consumida.
2. Beat fecha por `deadline` uma coorte expirada mesmo com fila vazia.
3. Finalização repetida não altera uma coorte já liberada.
4. Readiness observa a coorte da janela atual e expõe separadamente resíduos ativos expirados.
5. Nenhuma atribuição, replay, PATCH HubSpot ou alteração em produção faz parte do hotfix.

## Rollback

Reverter o commit do hotfix. Operacionalmente, manter `OPENING_COHORT_BARRIER_MODE=off` continua sendo o
kill switch; reconciliação das cinco linhas históricas exige autorização separada.

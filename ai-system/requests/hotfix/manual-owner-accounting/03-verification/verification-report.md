# Verificação do hotfix

## TDD e causalidade

- RED confirmado: os dois payloads reais representativos (`{}` e `sourceId` numérico sem
  `previousValue`) mantinham a origem com carga 1, o destino com carga 0 e não criavam
  `ConversationReassignment`.
- GREEN confirmado: ambos transferem A→B uma única vez usando a origem persistida e o owner confirmado.
- Evento com `previousValue` incompatível continua sem alterar o ciclo atual.
- O lock passou de origem/destino declarados para identidade do ticket; a projeção torna reentrega no-op.

## Execuções

- Casos direcionados de owner/ciclo/task: **22 passed**.
- Suíte `apps/support/tests/`: **420 passed, 38 skipped**.
- Suíte geral com integrações externas desabilitadas: **863 passed, 43 skipped**.
- Ruff format/check em todo o backend: limpo, **354 arquivos**.
- Mypy em `apps`, `core` e `common`: limpo, **355 arquivos**.
- Migration drift: `No changes detected`.
- `git diff --check`: limpo.

Os skips são testes que exigem PostgreSQL, Redis ou concorrência externa e já possuem marcação própria.
Nenhum teste foi conectado a banco ou provider não local.

## Observação do ambiente

A primeira execução geral teve uma falha isolada em
`test_client_requires_base_url`: o shell local tinha `SALOMAO_V1_BASE_URL` configurado e o teste exige
ausência da configuração. O mesmo teste e a suíte geral passaram com `SALOMAO_V1_BASE_URL=''`, que é o
isolamento esperado para esse cenário. Nenhum arquivo da integração Salomão foi alterado.

## Gate operacional pendente

O código está validado localmente, mas `OPENING_COHORT_BARRIER_MODE=enforce` não foi ativado. O gate
depende do deploy pelo usuário, alinhamento de SHA entre API/worker/Beat e smoke real controlado. A
ativação será uma operação separada após confirmação explícita de sucesso.

# Verificação

## TDD

- RED confirmado: o callback com fila vazia manteve a coorte em `active`.
- GREEN confirmado: callback libera por `all_settled` e fallback Beat libera por `deadline` sem fila.
- Readiness confirmado: resíduo histórico não substitui a coorte da janela atual.

## Execuções

- Regressões novas: `4 passed`.
- Testes de coorte + readiness: `25 passed, 5 skipped`.
- Suíte final `apps/support/tests/`: `418 passed, 38 skipped`.
- Ruff em `apps/support` e `core`: limpo.
- Mypy em `apps/support` e `core`: limpo (`140 source files`).
- Migration drift: `No changes detected`.

Os skips são integrações PostgreSQL/Redis já marcadas pela suíte; nenhuma base não local foi acessada.

## Validação causal independente

O papel obrigatório `staff-engineer` não pôde iniciar porque o modelo vinculado (`o3`) não é suportado pela
conta atual; o fallback `software-engineer` sofreu a mesma restrição com `gpt-4.1`. Um agente padrão
independente executou o mesmo checklist read-only e concluiu `FIXES THE BUG`, sem achados altos ou médios.

Achados baixos: o teste principal constrói a coorte já persistida em vez de reproduzir toda a criação em
`shadow`; e uma coorte expirada cujos membros já estabilizaram mantém a precedência histórica de
`all_settled` sobre `deadline`. Ambos preservam a correção de estado e não bloqueiam o hotfix.

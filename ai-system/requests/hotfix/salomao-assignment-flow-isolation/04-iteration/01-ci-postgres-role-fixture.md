# Iteração — fixture de papéis PostgreSQL no CI

## Falha observada

Workflow CI `30580371815`, job `90999246846`:

```text
FAILED apps/support/tests/test_operational_rls_migration.py::test_operational_rls_forward_reverse_forward
django.db.utils.ProgrammingError: role "anon" does not exist
```

Os demais 1.043 testes passaram e a cobertura atingiu 90,31%.

## Causa raiz

O teste de integração consultava `has_table_privilege` para `anon` e
`authenticated`, mas esses papéis cluster-wide não existem no PostgreSQL
efêmero do GitHub Actions. O container local possuía ambos os papéis, o que
mascarou o pré-requisito ausente.

A migration não apresentava o defeito: ela já ignora com segurança papéis que
não existem.

## Correção

O próprio teste agora cria `anon` e `authenticated` como papéis `NOLOGIN`
quando ausentes, antes de validar forward/reverse/forward. Isso torna a fixture
hermética e mantém a migration compatível com PostgreSQL sem papéis Supabase.

## Revalidação local

- PostgreSQL 16: 1.044 passed, 3 skipped.
- Cobertura: 90,32%.
- Ruff e format check do arquivo alterado: aprovados.

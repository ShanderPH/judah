# Iteração 02 — Railway RLS owner guard

## Incidente

O deployment Railway `ac9ef096-af5b-41f3-9f33-884ce72072a6`, no SHA
`7feb9cf299a352b5a1f23635f1ccab405f6f7cc0`, falhou no pre-deploy ao aplicar
`support.0026_protect_operational_tables_rls`.

Erro:

```text
django.db.utils.ProgrammingError: must be owner of table conversation_instances
```

## Causa raiz

A conexão usada pelo pre-deploy do serviço `judah` não é proprietária das
tabelas criadas no Supabase. `COMMENT ON TABLE`, `REVOKE` e
`ALTER TABLE ... ENABLE ROW LEVEL SECURITY` são operações reservadas ao
proprietário ou a um papel com autoridade equivalente.

## Correção

A migration agora:

1. identifica as tabelas existentes;
2. limita as operações às tabelas que o papel atual pode administrar;
3. emite aviso explícito para tabelas ignoradas;
4. permite que o deploy prossiga com aviso explícito de que o RLS não foi
   efetivamente aplicado pelo runtime;
5. mantém a aplicação privilegiada no gate Supabase separado já previsto no
   plano.

O hotfix não altera owner, `BYPASSRLS`, grants, flags ou dados de produção.

## Estado operacional observado

- `judah`: SHA anterior `eacdd2d0797949b31cdc493db996bed09f2f17a1`;
- `judah-worker`: SHA novo `7feb9cf299a352b5a1f23635f1ccab405f6f7cc0`;
- `judah-beat`: SHA novo `7feb9cf299a352b5a1f23635f1ccab405f6f7cc0`;
- readiness público: HTTP 200 servido pelo deployment web anterior;
- migration `support.0026`: não aplicada pelo deployment que falhou.

## Gate ainda separado

A proteção efetiva das 11 tabelas deve ser aplicada por uma conexão
proprietária no Supabase e verificada por grants, `relrowsecurity` e testes de
acesso de `anon`/`authenticated`. Este hotfix não autoriza essa mutação remota.
O registro Django de `support.0026` após o deploy não deve ser usado como prova
da proteção física: a verificação do schema vivo continua obrigatória.

## Verificação local

- PostgreSQL 16: `1045 passed, 3 skipped`;
- cobertura: `90.32%`;
- migration PostgreSQL forward/reverse/forward e guard sem ownership: `2 passed`;
- Ruff: aprovado;
- mypy: `Success: no issues found in 362 source files`;
- `git diff --check`: aprovado.

# Verificação 04 - Gate E

**Data:** 21 de julho de 2026
**Ambiente:** Python 3.14.4, Django 5.2.15, SQLite local descartável.

## Resultados

- Regressão Gates A-E: `70 passed in 6.73s`.
- Testes específicos do backfill/contrato: `5 passed in 4.73s`.
- `makemigrations --check --dry-run`: `No changes detected`.
- `manage.py check --fail-level WARNING`: `0 issues`.
- Ruff check: limpo.
- Ruff format: arquivos do Gate E formatados.
- `git diff --check`: limpo antes da atualização final dos artefatos.
- mypy 2.1.0: bloqueado por erro interno ao construir
  `NewSemanalDjangoPlugin`, condição já observada no Gate D.

## Critérios comprovados localmente

- dry-run executa e reverte;
- reexecução não cria ciclos nem vínculos duplicados;
- cursor, limite e filtro por ticket delimitam o lote;
- duas passagens fechadas do mesmo ticket preservam dois ciclos;
- timestamp ativo ausente é quarentenado, não inventado;
- schema de modelos e migrations não diverge.

## Não comprovado neste gate

- apply/reverse/reapply e constraints no PostgreSQL 16;
- contagens e ambiguidades de banco compartilhado;
- backfill em staging/produção;
- full suite e prontidão de release, que pertencem ao Gate F.

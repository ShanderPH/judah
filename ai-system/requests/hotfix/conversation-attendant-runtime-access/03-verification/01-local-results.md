# Verificação local

Data: 2026-09-09. Python 3.14.4, Django 5.2.15.

## Resultado final

- 24 testes passaram: migration/grants, histórico de atendentes e lifecycle/troca de owner.
- Ruff passou nos dois arquivos novos.
- mypy passou nos dois arquivos novos.
- `makemigrations --check --dry-run`: `No changes detected`.
- `git diff --check`: passou.

## Segurança verificada

- Apenas `judah_production_runtime` e `judah_staging_runtime` são elegíveis.
- Papéis ausentes são ignorados.
- Grants limitados a `SELECT, INSERT, UPDATE`; `DELETE` não é concedido.
- Migration não emite alteração de RLS, owner, policy, `PUBLIC`, `anon` ou `authenticated`.
- Reverse revoga exatamente os privilégios concedidos.

## Limitação

O Docker Desktop não estava disponível, portanto não houve teste local em PostgreSQL. A migration foi exercitada como
no-op no SQLite e seu SQL PostgreSQL foi validado por testes unitários. A execução real e a consulta de privilégios
devem ocorrer em staging antes de produção, conforme o runbook de deployment.

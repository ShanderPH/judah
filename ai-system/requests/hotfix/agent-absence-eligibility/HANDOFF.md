# Handoff — PR 75 remediation Gate A

## Resumo do implementado/corrigido

- Corrigida `support.0016` sem reescrever migration aplicada: o histórico
  compartilhado foi consultado em modo read-only e não contém `0015/0016`.
- Adicionada prova PostgreSQL 16 de apply, reverse, reapply, write permitido e
  veto SQLSTATE `42501` para runtime staging.
- CI agora cria banco PostgreSQL único por run, valida o alvo antes de migrar
  e executa a suíte real somente após migrations bem-sucedidas.
- Testes destrutivos recusam hosts remotos, nomes não descartáveis e bancos de
  outro workflow run antes do setup do pytest.
- Gate A passou localmente com 402 testes e 64,17% de cobertura; nenhuma
  mutation externa ou compartilhada foi executada.

## Arquivos modificados

- `.github/workflows/ci.yml`
- `apps/support/migrations/0016_block_non_authoritative_runtime_writes.py`
- `apps/support/tests/test_runtime_guard_migration.py`
- `common/database_safety.py`
- `common/tests/test_database_safety.py`
- `conftest.py`
- `ai-system/requests/hotfix/agent-absence-eligibility/02-artifacts/database/02-repair-runtime-guard-migration.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/02-artifacts/devops/07-postgres-ci-gate.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/03-verification/02-pr75-gate-a.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/STATUS.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/HANDOFF.md`

## Como testar localmente

Use somente PostgreSQL/Redis locais e descartáveis. O PostgreSQL deve usar o
database `judah_test`.

```powershell
$env:DJANGO_ENV='test'
$env:DJANGO_SECRET_KEY='local-test-only'
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55432/judah_test'
$env:REDIS_URL='redis://127.0.0.1:56379/0'

uv run python -m common.database_safety
uv run python manage.py migrate --run-syncdb
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
git diff --check
```

As demais variáveis obrigatórias devem receber apenas placeholders locais,
conforme `.github/workflows/ci.yml`.

## Riscos conhecidos / áreas frágeis

- A migration `0016` ainda implementa a cerca denylist original. A troca por
  roles PostgreSQL explicitamente confiáveis pertence a DB-03/Gate B.
- GitHub-hosted checks do SHA final ainda não rodaram porque nenhum commit ou
  push foi autorizado nesta execução.
- O gate local usou PostgreSQL 16, enquanto o HelpdeskDB compartilhado reporta
  PostgreSQL 17; nenhum teste foi executado no banco compartilhado.
- O restante da remediação (queue gates, durable attempts, canonicalização e
  rollout) permanece intencionalmente fora deste slice.

## Pontos de integração críticos

- VERIFY deve confirmar que o nome dinâmico do database é idêntico no
  `DATABASE_URL` e em `POSTGRES_DB`.
- O teste de migration deve continuar recriando `MigrationExecutor` a cada
  transição.
- Não executar pytest se `common.database_safety` rejeitar o alvo.
- Não avançar para Gate B, migration compartilhada, credenciais, deploy ou
  rollout sem a próxima autorização prevista no plano.

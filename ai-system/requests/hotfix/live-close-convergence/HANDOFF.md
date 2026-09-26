# Handoff do P0 live

PR draft: https://github.com/ShanderPH/judah/pull/127

## Resumo

- A observação de provider só fecha occupancy de um ciclo ativo quando o fechamento do ciclo e a `ClosedConversation` são materializados na mesma transação.
- O fluxo de ocorrência lê o provider fora dos locks, revalida a revisão e confirma occupancy, ciclo, filas, lifecycle e capacidade em um único boundary.
- Falha inesperada no lifecycle provoca rollback e permite retry; falta de writer authority também faz a task falhar de modo observável.
- Resultados estruturados distinguem classificação e aplicação; readiness conta divergências recentes sem modificar dados.
- Nenhum reparo histórico ou escrita em produção foi executado.

## Arquivos modificados

- `apps/support/ticket_close_service.py`
- `apps/support/owner_reconciliation_service.py`
- `apps/support/auto_assign_service.py`
- `apps/support/tasks.py`
- `apps/support/assignment_readiness.py`
- `apps/support/tests/test_ticket_close_service.py`
- `apps/support/tests/test_tasks_extended.py`
- `ai-system/requests/hotfix/live-close-convergence/` (plano, diagnóstico, verificação e rollout)

## Como testar localmente

Com Python 3.14 e dependências do projeto instaladas:

```bash
ruff format --check .
ruff check .
DJANGO_ENV=test DJANGO_SECRET_KEY=test DATABASE_URL=sqlite:///./.test.sqlite3 mypy apps core common
python run_tests_local.py
DJANGO_ENV=test DJANGO_SECRET_KEY=test DATABASE_URL=sqlite:///./.test.sqlite3 OPENAI_API_KEY=sk-test-placeholder PINECONE_API_KEY=test-placeholder HUBSPOT_ACCESS_TOKEN=test-placeholder HUBSPOT_APP_SECRET=test-placeholder python manage.py makemigrations --check --dry-run
git diff --check
```

Concorrência PostgreSQL: usar `JUDAH_TEST_DATABASE_URL` apontando **somente** para `judah_test` local e rodar os três casos `test_postgres_concurrent_close_converges`. O runner recusa banco remoto e o `conftest.py` apaga dados no banco de teste.

## Riscos conhecidos e pontos de integração para VERIFY

- Eventos já processados antes do fix continuam no backlog; o detector não repara dados.
- `ConversationEvent.PROCESSED` continua significando consumo/dispatch. Correlacionar `source_event_id` com o log canônico da task.
- Conferir em produção a configuração de authority no worker. Um worker sem permissão esgota retries e exige correção da configuração ou roteamento.
- Verificar primeiro a transação conjunta de `reconcile_ticket` e `apply_close_occurrence`, o caminho de owner/portfolio e a retomada após falha de lifecycle.

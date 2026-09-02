# Handoff

## Resumo do implementado/corrigido

- Hidratação agora bloqueia e atualiza o envelope persistido pelo seu UUID.
- Callers sem envelope convergem por insert-on-conflict, sem `IntegrityError`
  como fluxo normal.
- A atomicidade entre estado do ledger e criação do outbox foi preservada.
- Falhas concorrentes da hidratação não rebaixam `READY` ou `IGNORED`.
- Nenhuma mudança foi feita no schema ou no incidente n8n/`DEAD_LETTER`.

## Arquivos modificados

- `apps/webhooks/n8n_inbound.py`
- `apps/webhooks/reconciliation.py`
- `apps/webhooks/tests/test_n8n_inbound.py`
- `apps/webhooks/tests/test_reconciliation.py`
- `apps/webhooks/tests/test_n8n_concurrency.py`
- `ai-system/requests/hotfix/webhook-hydration-upsert/*`

## Como testar localmente

```powershell
uv run ruff check apps/webhooks
uv run ruff format --check apps/webhooks
uv run mypy apps/webhooks
uv run python run_checks.py
uv run python run_tests_local.py
```

Para PostgreSQL 16 local descartável:

```powershell
$env:JUDAH_TEST_DATABASE_URL='postgresql://judah:<local-password>@127.0.0.1:5432/judah_test'
uv run python run_tests_local.py
```

Nunca executar a suíte contra Supabase ou outro banco compartilhado.

## Riscos conhecidos / áreas frágeis

- O gate concorrente PostgreSQL 16 passou; a confirmação pós-deploy continua
  obrigatória porque o perfil de carga de produção não é reproduzido localmente.
- O mypy 2.1.0 falha ao construir `NewSemanalDjangoPlugin`, antes de analisar o
  código; esse gate de tooling permanece pendente.
- `ON CONFLICT DO NOTHING` ainda pode aguardar uma transação concorrente no
  índice único, embora não deva gerar `23505`.

## Pontos de integração críticos

- Revalidar cardinalidade de ledger/outbox e ausência de `23505` após o deploy.
- Confirmar que `READY` sempre possui um outbox e `IGNORED` não possui.

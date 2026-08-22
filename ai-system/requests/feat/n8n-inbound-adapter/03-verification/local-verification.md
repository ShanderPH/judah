# Local verification

## Passed

- `run_checks.py`: migrations applied to isolated SQLite, no pending migrations,
  Django system check clean.
- `run_tests_local.py`: 742 passed, 15 skipped, 90.04% coverage. The skipped
  cases include PostgreSQL-only contention coverage unavailable in the default
  isolated SQLite run.
- Webhooks and HubSpot client focused suite: 77 passed, 3 PostgreSQL-only tests
  skipped in the SQLite environment.
- `ruff check .`: clean.
- `ruff format --check .`: 340 files already formatted.
- Celery task discovery: all four new tasks registered; existing Beat schedule
  loaded with 11 entries and no new automatic poller.
- `git diff --check`: clean.
- PostgreSQL local descartável: `test_n8n_concurrency.py` passou com 3/3 casos,
  incluindo dois outboxes concorrentes para a mesma thread com exatamente um
  claim. A instalação limpa das migrations `0007` e `0008` também passou.
- Verificador dos workflows n8n: 27/27 checks passaram, incluindo HMAC,
  expiração, idempotência, concorrência lógica e ausência de secrets nos
  exports.
- Matriz do contrato real com `serialize_payload()`, `sign_payload()`, headers
  e classificação de respostas: 14/14 casos passaram.
- Smoke sintético JUDAH -> webhook n8n controlado: uma única requisição recebeu
  HTTP 202, preservou o `event_id` e transitou `PENDING -> PROCESSING ->
  DELIVERED`. Esse smoke não representa um fluxo iniciado por mensagem real do
  HubSpot.

## Not passed / environment limitation

- `mypy`: internal plugin construction error in mypy 2.1.0 / mypy-django on
  Python 3.14, before source analysis.
- RLS e permissões da role real continuam dependendo do gate de staging; o gate
  local não autoriza ativação.

Os bancos PostgreSQL locais descartáveis foram removidos após o teste. Nenhum
banco externo, app HubSpot, workflow n8n ativo, serviço Railway, deploy ou merge
foi alterado.

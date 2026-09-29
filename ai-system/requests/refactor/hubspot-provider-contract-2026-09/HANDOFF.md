# Handoff para VERIFY

## Gate operacional de scopes e preflight — 2026-09-29

- Manifesto do app agora explicita `crm.objects.tickets.read`, `crm.objects.tickets.write` e `crm.objects.owners.read`; preserva `tickets` e os scopes de Conversations já publicados.
- Comando `check_hubspot_provider_contract` roda em `off`, só faz GET, produz JSON sem PII/token e falha quando portal, capability obrigatória ou roster não passa.
- Build HubSpot 21 publicado no portal `47354717` e app estático reinstalado; readback de app/webhooks sem drift obrigatório. Webhooks publicados foram preservados byte a byte.
- Preflight com token real: quatro leituras obrigatórias `available`, time `54655589`, roster completo com 7 membros ativos e zero owners ausentes; `tickets_write=unverified`.
- `READY_FOR_SHADOW=true` como gate técnico para revisão. Nenhuma flag foi promovida, nenhum PATCH/POST/DELETE CRM foi feito, nenhum backend foi implantado.

**Arquivos deste gate:** `hubspot-app/src/app/app-hsmeta.json`, `apps/integrations/hubspot/team_roster.py`, `apps/support/management/commands/check_hubspot_provider_contract.py`, `apps/support/tests/test_hubspot_provider_preflight.py`, `ai-system/requests/refactor/hubspot-provider-contract-2026-09/{00-context/hubspot-capability-matrix.md,03-verification/*,STATUS.md,HANDOFF.md}`.

**Primeiro VERIFY:** repetir o preflight com credential Railway em `mode=off`, conferir `portal.matches_expected`, `roster.complete`, `owners_read` e exit code; comparar downloads oficiais do build publicado com manifests. Não executar suíte pytest contra banco não local. Mutation de tickets somente em sandbox antes de ENFORCE.

## Implementado

- Registry de capabilities, transporte HTTP tipado, preflight e adapter versionado de Tickets selecionado em `enforce`.
- Roster de Teams/Users/Owners paginado, com resultado parcial explícito, remoção/inativação e cache do último sync completo.
- Ocorrência de lifecycle com constraints, guard PostgreSQL, entrada/fechamento/owner comprovados e reconciliação bounded quando fechamento ou ciclo do owner ainda não se materializaram.
- Readiness de capability/roster/webhook, comparação desired/published e bloqueio de novos owner effects em `enforce` quando prova obrigatória ou writer canônico de capacidade falta.
- Horários de atribuição/transferência observados por snapshot sem prova ficam nulos pela migration `0035`; durações derivadas não são inventadas.
- Schemas Ninja aceitam os horários nulos. PostgreSQL 16 local validou forward, reverse em banco vazio, novo forward e dois INSERTs nulos revertidos.
- Agregadores em `enforce` contam ciclos e deduplicam fechamento/atribuição. Transferência só conta para o agente anterior quando uma mensagem outbound humana, dentro da posse, comprova participação. Os modos anteriores preservam as séries legadas para comparação.
- Classificação `unknown_external` para mudança de owner sem ator/attempt comprovado.

## Arquivos modificados

Ver `git diff --name-only` e `git status --short` na branch; arquivos novos relevantes em `apps/integrations/hubspot/`, `apps/support/lifecycle_occurrence_service.py`, `apps/support/provider_readiness.py` e `apps/support/migrations/0033_*` a `0035_*`. Os arquivos preexistentes alterados `docker-compose.yml` e `webapp/package*.json` não fazem parte desta request.

## Como testar localmente

```bash
DJANGO_ENV=test DATABASE_URL=sqlite:///./.test.sqlite3 SALOMAO_V1_BASE_URL='' .venv/bin/python -m pytest -q
.venv/bin/ruff check apps/integrations/hubspot apps/support apps/webhooks core/settings/base.py
.venv/bin/mypy .
DJANGO_ENV=test DATABASE_URL=sqlite:///./.test.sqlite3 SALOMAO_V1_BASE_URL='' .venv/bin/python manage.py check
DJANGO_ENV=test DATABASE_URL=sqlite:///./.test.sqlite3 SALOMAO_V1_BASE_URL='' .venv/bin/python manage.py makemigrations --check --dry-run
```

PostgreSQL/Redis/Celery locais exigem serviços locais, como registrado em `03-verification/local-results.md`. Nunca apontar a suíte para banco não local: `conftest.py:isolate_db` apaga dados.

Depois de definir `LOCAL_TEST_DATABASE_URL` para uma instância PostgreSQL descartável em `localhost` e `JUDAH_CAPACITY_REDIS_URL` para Redis local, executar:

```bash
DJANGO_ENV=test DATABASE_URL="$LOCAL_TEST_DATABASE_URL" .venv/bin/python -m pytest -q apps/support/tests/test_capacity_postgres.py::test_last_slot_has_one_held_reservation apps/support/tests/test_ticket_close_service.py::test_postgres_concurrent_close_converges apps/support/tests/test_provider_contract_red.py::test_occurrence_table_has_postgres_runtime_guard
DJANGO_ENV=test DATABASE_URL="$LOCAL_TEST_DATABASE_URL" JUDAH_CAPACITY_REDIS_URL=redis://127.0.0.1:6379/15 .venv/bin/python -m pytest -q apps/support/tests/test_capacity_celery.py
```

## Riscos e primeiros pontos de VERIFY

- Leituras reais Tickets 2026-09, Teams/Users/Owners e webhook publicado foram verificadas com token de produção e download do build 21. PATCH de Tickets segue sem validação sandbox.
- ARCH-03 ainda aberto. Mensagens históricas sem prova de ator não foram reprocessadas; owner anterior fica fora da métrica. Validar `A-<hubspot_user_id>` e o vínculo thread/ticket no sandbox. Medir custo da agregação histórica em shadow.
- Reverse de `0035` só é seguro antes de persistir horários nulos; não usar como rollback de produção.
- Conferir permutações de reopen/owner/close e source do attendant; comparar shadow antes de qualquer `enforce`.
- Default `off` preserva adapter legado; fechamento sem horário lança `CloseProjectionError` para manter o retry explícito. `shadow` e `enforce` registram fechamento pendente para reconciliação.

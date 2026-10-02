# Handoff para VERIFY

## Release conjunto #134/#135 — continuação do proof

Não promover #134 isoladamente. A fonte desejada agora é contrato privado de `HUBSPOT_PROVIDER_CONFIG_JSON`; antes de promover, validar contrato privado, readback publicado novo, substituição do writer legado e todos os gates do SHA final. A concorrência terminal na entrada de #134 foi corrigida na revisão de #135, com regressão permanente e contenção real PostgreSQL. Evidências atuais: `ai-system/requests/hotfix/hubspot-webhook-proof-durability/03-verification/review-comments.md`, relativo à raiz do checkout.

## Hotfix do PR #134 — 2026-10-02

- Corrigidas entradas comprovadas pending sem agendamento: criação agenda e scanner recupera entradas sem horário, dentro do orçamento existente.
- Retry de entrada agora chama o writer canônico de abertura; não interpreta entrada como fechamento. Conflito, stale e evidência insuficiente permanecem bounded e não alteram ciclo mais novo.
- Next.js e preset ESLint atualizados para 16.3.8 com lockfile validado por `npm ci`; auditoria de produção sem vulnerabilidades.
- 12 casos de regressão de entrada adicionados. Suíte completa SQLite: 1.016 passed / 50 skipped, cobertura 90,75%; regressões PostgreSQL local: 52 passed. WebApp: 66 testes e build aprovados; Ruff/mypy/Django/migration drift aprovados.

**Arquivos:** `apps/support/{lifecycle_occurrence_service.py,tasks.py,tests/test_lifecycle_entry_recovery.py}`, `webapp/{package.json,package-lock.json}` e os artefatos desta request. Checkout: `/tmp/judah-pr134-review`.

**Como testar:** comandos exatos e avisos não bloqueantes em `03-verification/pr-134-hotfix-review.md`. Plano e critérios em `01-plan/pr-134-hotfix.md`.

**Primeiro VERIFY:** revisar o ramo de entrada, idempotência por identidade temporal, conflito/stale, budgets e exclusão de repair. As três entradas antigas expiradas serão classificadas como repair; não declarar recuperação de produção com base nos testes locais. Recovery dos 229 owners e 15 closes continua separado. V-03/ARCH-03 permanecem abertos; conferir deployments reais, pois CD contém passos placeholder.

## Baseline pós-deploy — 2026-10-02

- Produção e `main` convergiram no SHA `0ca25b842ef55607af210419a8c17c4b56d6074f` do PR #133; API, worker e beat estão com deployment SUCCESS.
- A migration `0036` está aplicada em produção e o CHECK físico aceita os valores históricos e canônicos de provenance.
- Roster local pós-hotfix: 7 agentes ativos no time N1, nenhum sem owner ID; 8 agentes ativos no total com owner ID e CRM user ID.
- Baseline de invariantes: zero double-cycle live, zero duplicate occupancy, zero duplicate assignment log por ticket/cycle e zero drift de capacidade nos agentes ativos.
- Pós-cutover, assignments materializados convergem: 49 automáticos `confirmed_by_read`; logs `unknown_external` permanecem sem attempt artificial e com cycle.
- Novo blocker operacional: 229 `owner_changed` estão em `repair_required`; 24 dessas ocorrências hoje já cabem temporalmente em um ciclo válido, mas `repair_required` não é retomado pelo scanner automático.
- Há ainda 3 `entered_support_queue` em `pending`, sem `next_reconcile_at`, sem retry e sem ciclo exato. Esse estado não entra no scanner atual e precisa de classificação.
- Relatório detalhado: `03-verification/post-deploy-baseline-2026-10-02.md`.
- Nenhum replay, repair, backfill, mutation HubSpot ou novo deploy foi executado nesta etapa.

**Próximo VERIFY:** classificar o backlog de lifecycle e fechar a lacuna de convergência antes do V-03 sandbox/canário final.

## Atualização de provenance — 2026-09-30

- `AssignmentLog` agora declara CHECK compatível com três valores legados e seis valores canônicos; migration `0036` troca o CHECK físico sem janela sem validação e guarda a presença anterior para reverse.
- Regressão PostgreSQL reproduz o CHECK legado, testa forward/reverse e acompanha owner observado sem prova de ator por occurrence, ciclo, occupancy, capacidade e retry.
- Auditoria de ARCH-03 e plano pós-merge estão em `03-verification/architecture-audit.md` e `05-deployment/release-and-rollback.md`.

**Arquivos desta atualização:** `apps/support/models.py`, `apps/support/migrations/0036_assignment_log_provenance_check.py`, `apps/support/tests/test_assignment_provenance_postgres.py`, `ai-system/requests/refactor/hubspot-provider-contract-2026-09/{STATUS.md,HANDOFF.md,03-verification/architecture-audit.md,05-deployment/release-and-rollback.md}`.

**Teste local:** `SALOMAO_V1_BASE_URL= .venv/bin/python run_tests_local.py`; para PostgreSQL 16 local descartável, `DJANGO_ENV=test DATABASE_URL=<URL-local-judah_test> .venv/bin/pytest apps/support/tests/test_assignment_provenance_postgres.py -q --no-cov`. Nunca apontar testes para banco não local.

**Gates locais:** suíte SQLite: 1003 passed / 50 skipped, cobertura 90,69% (piso 90%); suíte PostgreSQL 16: 1047 passed / 6 skipped. Após ajustes finais de docstrings e tipagem, regressão PostgreSQL: 3 passed; Ruff check/format, mypy (`apps core common`), Django checks e migration drift aprovados. As suítes completas precedem esses ajustes de documentação e tipagem; a regressão focada valida a versão final.

**Docstrings:** auditoria AST dos dois módulos novos: 10/10 definições documentadas (módulos, classe e funções, incluindo helpers privados). Funções públicas da migration possuem parâmetros/retorno tipados e docstrings com argumentos e falhas de rollback.

**Primeiro VERIFY:** conferir CHECK após `0036`, papel `judah_schema_migration` e ausência de dupla gravação por rota; executar canário com readback e comparar contagens por ciclo. Reverse é bloqueado quando já existem valores canônicos exclusivos. `48989048943` está sem owner atual; não criar atribuição histórica sem prova do provider.

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

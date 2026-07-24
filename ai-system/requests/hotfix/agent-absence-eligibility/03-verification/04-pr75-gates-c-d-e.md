# PR 75 — Gates C, D e E

## Resultado

Os Gates C e D foram implementados e o Gate E está aprovado localmente e no
GitHub para o SHA de implementação
`3bbc0649ed7249a163de7a11ad498cc25ec552fe`.

## Gate C — protocolo durável

- `AssignmentAttempt` persiste idempotency key, ticket, fila, agente, revisão de
  elegibilidade, owner desejado/anterior, snapshot redigido, estado, resultado
  do provider, timestamps e política de retry.
- Claims duráveis vivem em `NewConversation`, com token de owner e expiração.
- Reserva de capacidade e criação da tentativa ocorrem sob locks PostgreSQL e
  antes de qualquer mutação HubSpot.
- A chamada HubSpot ocorre sem transação de banco aberta.
- Finalize e compensate são idempotentes; capacidade usa piso zero.
- Resultado ambíguo é reconciliado pela leitura do owner antes de retry ou
  `repair_required`.
- Celery e `repair_assignment_attempts` convergem tentativas após crash.
- Locks Redis usam token aleatório e compare-delete Lua; o banco continua sendo
  a fronteira de correção.
- Retenção terminal de 30 dias roda em lotes limitados.

## Gate D — caminhos canônicos e provider

- Removidos os corpos legados inalcançáveis do SAT e de `attempt_auto_assign`.
- O Matchmaker encaminha toda atribuição automática ao protocolo durável.
- A Users API diferencia 404, 401, 403, 429, timeout, 5xx e payload malformado.
- GETs usam retry limitado, jitter e `Retry-After`.
- A validação captura um único `now` por decisão.
- A atribuição manual não persiste sucesso local quando o HubSpot falha.
- Force reassign exige motivo não vazio e preserva auditoria.
- `/queue/health/` inclui readiness legível por máquina para autoridade,
  postura de flags, migration, frescor SAT, identidade do writer e tentativas
  travadas.

## Gate E — evidência local

Ambiente revalidado em 2026-07-20: Python 3.14.4, PostgreSQL 16 local
descartável `judah-db-1`, banco `judah_test`, Redis 7 `judah-redis-1`.

```text
common.database_safety:
  Safe test database: backend=postgresql host=localhost name=judah_test
migrate --run-syncdb:
  support.0015 ... OK
  support.0016 ... OK
  support.0017 ... OK
pytest: 427 passed in 33.01s
ruff check .: All checks passed
ruff format --check .: 253 files already formatted
mypy .: Success: no issues found in 250 source files
manage.py check --fail-level WARNING: no issues
makemigrations --check --dry-run: No changes detected
git diff --check: clean
```

Testes específicos de concorrência e crash-boundary no PostgreSQL foram
repetidos três vezes:

```text
run 1: 4 passed
run 2: 4 passed
run 3: 4 passed
```

Incluem dois workers/um ticket, dois workers/último slot, redelivery idempotente
e crash após sucesso externo antes do finalize. A suíte completa também cobre
corrida de revisão, compensate repetido, 404 e a matriz de resultados da Users
API.

## Gate E — evidência hospedada

PR: `https://github.com/ShanderPH/judah/pull/75`

SHA de implementação verificado:
`3bbc0649ed7249a163de7a11ad498cc25ec552fe`.

GitHub Actions run: `29762444783`.

O job `Tests (Python 3.14)` confirmou:

```text
Safe test database:
  backend=postgresql host=localhost name=judah_ci_29762444783_1
PostgreSQL service: postgres:16-alpine
support.0015 ... OK
support.0016 ... OK
support.0017 ... OK
427 passed in 19.64s
Total coverage: 64.76% (required: 50%)
```

Checks requeridos observados no head:

```text
Lint & Type Check: SUCCESS
Tests (Python 3.14): SUCCESS
Security Scan: SUCCESS
Django System Checks: SUCCESS
Vercel: SUCCESS
Vercel Preview Comments: SUCCESS
```

O `mergeStateStatus=BLOCKED` decorre de `reviewDecision=REVIEW_REQUIRED`, não de
falha de CI.

## Correção do CI basal

O SHA anterior falhava porque o writer guard aceitava apenas `judah_test`, mas
o GitHub usa `test_judah_ci_<run>_<attempt>`. A regex agora aceita somente esses
nomes efêmeros bem formados, mantendo application name e identidade local
restritos. O teste genérico de segurança também deixa de herdar `GITHUB_ACTIONS`.

## Não executado

- Nenhuma migration, role/grant, credencial, flag ou deploy compartilhado.
- Gate F não foi iniciado; rollout exige aprovação explícita do Felipe.

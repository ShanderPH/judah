# PR 75 — Gates C, D e E

## Resultado

Os Gates C e D foram implementados e o Gate E local está aprovado. O fechamento
do Gate E hospedado depende de publicar este diff na PR 75 e observar os checks
do novo SHA.

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

## Gate E — evidência

Ambiente: Python 3.14.4, PostgreSQL local descartável `judah-db-1`.

```text
pytest: 427 passed in 45.48s
ruff check .: All checks passed
ruff format --check .: 253 files already formatted
mypy .: Success: no issues found in 250 source files
manage.py check --fail-level WARNING: no issues
makemigrations --check --dry-run: No changes detected
git diff --check: clean
```

Testes específicos do protocolo no PostgreSQL:

```text
16 passed
```

Incluem dois workers/um ticket, dois workers/último slot, corrida de revisão,
redelivery idempotente, compensate repetido, 404, crash após sucesso externo e
antes do finalize, além da matriz de resultados da Users API.

## Correção do CI basal

O SHA anterior falhava porque o writer guard aceitava apenas `judah_test`, mas
o GitHub usa `test_judah_ci_<run>_<attempt>`. A regex agora aceita somente esses
nomes efêmeros bem formados, mantendo application name e identidade local
restritos. O teste genérico de segurança também deixa de herdar `GITHUB_ACTIONS`.

## Não executado

- Nenhuma migration, role/grant, credencial, flag ou deploy compartilhado.
- Nenhum commit ou push dos Gates C–E; requer autorização explícita.
- Checks hospedados do novo SHA ainda não existem.

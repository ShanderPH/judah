# Verificação local — INCIDENT-48108294672

Data: 2026-09-01. Ambiente totalmente local, sem HubSpot, staging ou produção.

## Topologia

- Python 3.14.4
- Django 5.2.15
- PostgreSQL 16.13 (`judah-db-1`)
- Redis 8.6.5 (`judah-redis-1`)
- Celery 5.6.3, worker não-eager com pool de threads e concurrency 4

## Evidência red → green do enum

Antes de BE-01, os caminhos normal e off-hours falharam com PostgreSQL `DatatypeMismatch` ao usar `bulk_update` contra `agent_status_enum`. Após o split escalar, a suite física passou e restaurou a coluna para `character varying(20)` no teardown.

## Execuções verdes

- 9 testes do contrato enum/SAT: transições, sem write escalar quando unchanged, 8/50/500 agentes, rollback, fencing e lease concorrente.
- 43 testes SAT/eligibility existentes.
- 22 testes durable assignment/error catalog PostgreSQL após BE-02/03.
- 39 testes BE-04 readiness/repair/command PostgreSQL.
- 81 testes SEC-01 de sinks, settings, SAT, tasks, assignment e webhooks.
- 79 testes consolidados BE-04/OBS-01 PostgreSQL.
- 30 testes BE-05 HubSpot/Jira/n8n.
- 1 teste worker Celery real: overlap SAT + 9 deliveries concorrentes.
- 40 testes integrados finais: worker, Redis locks, enum físico, saga concorrente, n8n locks e Beat config.
- 166 testes na regressão consolidada final em PostgreSQL/Redis locais.
- Ruff e pre-commit passaram em todos os commits.
- Ruff global: 338 arquivos formatados e lint clean; `makemigrations --check --dry-run`: `No changes detected`.
- Mypy 2.1.0: `Success: no issues found in 339 source files`, usando o mesmo ambiente de teste definido na CI.
- Suíte PostgreSQL completa após o ajuste de tipagem: 789 passed, 4 skipped, cobertura 90,71%; os 9 testes do enum físico passaram.

## Provas de invariantes

- Uma única chamada provider em duas heartbeats concorrentes; segunda execução retorna `skipped_locked`.
- Oito tickets produzem oito attempts; uma delivery duplicada não cria attempt adicional.
- Soma de capacidade igual a oito, sempre entre zero e máximo por agente.
- `external_applied` exige GET/readback e nunca repete PATCH.
- Compensate/finalize concorrentes afetam capacidade e projeções uma vez.
- Readiness e métricas contêm apenas agregados e labels de enum controlado.
- Liveness não chama readiness de assignment e permanece `alive` diante de falha do domínio.

## Gate de type check

O erro inicial de construção do plugin foi reproduzido com traceback e causado pela ausência local de `DJANGO_ENV=test` e das variáveis placeholder que a CI já fornece. Com o ambiente equivalente ao workflow, o plugin analisou o projeto e revelou uma única anotação incorreta no teste novo. A anotação passou a importar o tipo público `pytest_django.DjangoDbBlocker`; depois disso, o gate ficou verde:

```text
Success: no issues found in 339 source files
```

## Auditoria de flake concorrente

A primeira regressão consolidada terminou com 165 passes e uma falha em um teste concorrente preexistente: um thread não encontrou o Agent entre duas leituras. Sem alterar código, o caso focal passou 3/3 e a regressão consolidada repetida passou 166/166. A evidência aponta isolamento/timing do harness; o risco residual fica registrado para CI, sem mascarar ou adicionar retry automático.

## Gates externos e bloqueios atuais

- PR #116 publicada; CI inicial totalmente verde: WebApp, lint/type check, Django system checks, Security Scan e testes Python 3.14.
- Merge bloqueado pela proteção da `main`: `REVIEW_REQUIRED`, sem reviews registrados.
- SP-06: concluído read-only; build remoto #20 corresponde semanticamente a `Judah HubSpot Integration/`.
- INT-01: bloqueado porque a fonte operacional comprovada é drift não rastreado e o plano exige manifesto canônico versionado.
- V-04: bloqueado por INT-01 e pela ausência do projeto `inchurch-sandbox` na conta autenticada.
- Push, PR, merge, deploy, migrations externas, flags e recovery continuam não executados.

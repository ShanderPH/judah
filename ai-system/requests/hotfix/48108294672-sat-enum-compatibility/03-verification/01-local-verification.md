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

## Provas de invariantes

- Uma única chamada provider em duas heartbeats concorrentes; segunda execução retorna `skipped_locked`.
- Oito tickets produzem oito attempts; uma delivery duplicada não cria attempt adicional.
- Soma de capacidade igual a oito, sempre entre zero e máximo por agente.
- `external_applied` exige GET/readback e nunca repete PATCH.
- Compensate/finalize concorrentes afetam capacidade e projeções uma vez.
- Readiness e métricas contêm apenas agregados e labels de enum controlado.
- Liveness não chama readiness de assignment e permanece `alive` diante de falha do domínio.

## Limitação do type check

O comando focal `uv run mypy ...` termina antes de analisar os arquivos:

```text
mypy 2.1.0 INTERNAL ERROR
Error constructing plugin instance of NewSemanalDjangoPlugin
```

Isso é um blocker de tooling preexistente, não um erro de tipo emitido pelo código alterado. Deve ser corrigido antes do gate de merge.

## Auditoria de flake concorrente

A primeira regressão consolidada terminou com 165 passes e uma falha em um teste concorrente preexistente: um thread não encontrou o Agent entre duas leituras. Sem alterar código, o caso focal passou 3/3 e a regressão consolidada repetida passou 166/166. A evidência aponta isolamento/timing do harness; o risco residual fica registrado para CI, sem mascarar ou adicionar retry automático.

## Gates não executados

- SP-06: leitura externa HubSpot não autorizada.
- INT-01: bloqueada por SP-06 e confirmação humana da fonte canônica.
- V-04: staging/sandbox não autorizado.
- Push, PR, merge, deploy, migrations externas, flags e recovery: não executados.

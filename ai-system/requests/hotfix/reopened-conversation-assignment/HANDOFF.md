# HANDOFF - Gate G implementation (OPS-01 a OPS-03)

**Request:** `hotfix/reopened-conversation-assignment`
**Data:** 21 de julho de 2026
**Estado:** Gate G implementado localmente; marcos externos não executados.

## Resumo do implementado/corrigido

- Readiness agora calcula `enforcement_ready` sem PII e sinaliza linhas legadas,
  mismatches e ciclos em fila sem dispatch.
- O probe de plataforma expÃµe a postura agregada de ciclos sem transformar
  enforcement em teste de produÃ§Ã£o.
- O rollout expand/migrate/contract possui marcos, stop conditions e rollback
  versionados em `05-deployment/01-gate-g-rollout.md`.
- Identidade explícita de ciclo cobre ingresso, fila, reserva, atribuição,
  fechamento, reatribuição, reparo, logs e métricas.
- Reentrada legítima cria outro ciclo e preserva os históricos anteriores;
  retry, evento stale e tentativa de ciclo antigo falham de forma idempotente.
- Backfill é determinístico, paginado, reiniciável, auditável e fail-closed
  para ambiguidades, sem consultar HubSpot por padrão.
- Migration de contrato remove unicidades ticket-wide incompatíveis, mantém
  constraints por ciclo e impede rollback que destruiria histórico válido.
- Runbook documenta backfill, queries de cobertura, invariantes e rollback
  funcional não destrutivo.

## Arquivos críticos

- `apps/support/conversation_cycle_service.py`
- `apps/support/legacy_cycle_backfill.py`
- `apps/support/durable_assignment_service.py`
- `apps/support/migrations/0020_conversation_cycles_expand.py`
- `apps/support/migrations/0021_cycle_assignment_invariants.py`
- `apps/support/migrations/0022_closed_conversation_multi_cycle.py`
- `apps/support/migrations/0023_cycle_backfill_contract.py`
- `apps/support/tests/test_gate_e_contract_migration.py`
- `docs/operations/absence-safe-assignment.md`

## Verificação executada

- PostgreSQL 16.14 + Redis 7 descartáveis: `531 passed in 56.18s`.
- Lane PostgreSQL focada A-E: `80 passed in 22.14s`.
- Migration `0023`: apply/reverse/reapply e rollback inseguro recusado.
- Ruff check: limpo; Ruff format: 274 arquivos conformes.
- mypy: `Success: no issues found in 270 source files`.
- Django check: 0 issues; migration drift: nenhum.
- `git diff --check`: limpo.

## Como repetir

Use exclusivamente PostgreSQL/Redis locais descartáveis e uma
`DATABASE_URL` aceita por `common.database_safety`:

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy apps common core
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
git diff --check
```

## Riscos conhecidos / integração crítica

- O Gate F prova prontidão técnica local, não qualidade de dados de staging ou
  produção. O dry-run e as ambiguidades reais ainda precisam de aprovação e
  revisão humanas no Gate G.
- FKs permanecem nulas durante versão mista; enforcement só pode ser ligado
  após readiness confirmar zero writers antigos e cobertura aceitável.
- Deploy, migrations compartilhadas, flags, canário, backfill e reparo de
  tickets do incidente continuam fora desta autorização.

## Próxima ação

Felipe: autorizar separadamente o marco G1, deploy aditivo com
`CONVERSATION_CYCLES_ENFORCED=false`. Não inferir G2-G7, backfill compartilhado,
canário, enforcement ou reparo externo a partir desta implementação.

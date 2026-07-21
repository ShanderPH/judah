# Verificação 05 - Gate F

**Data:** 21 de julho de 2026
**Ambiente:** PostgreSQL 16.14 e Redis 7 locais descartáveis; Python 3.14.4,
Django 5.2.15. Nenhuma base compartilhada ou API externa foi acessada.

## Resultado consolidado

| Gate | Resultado |
|---|---|
| Domínio e idempotência | verde |
| Concorrência PostgreSQL e locks | verde |
| Saga, compensate e repair | verde |
| Migrations e backfill | verde |
| Webhooks, HubSpot client, Celery, SAT, admin e AI lifecycle | verde |
| Quality gates | verde |

## Evidência

- Suíte completa PostgreSQL: `531 passed in 56.18s`.
- Regressão focada de ciclos: `80 passed in 22.14s`.
- Migration de contrato `0023`: apply, reverse limpo, reapply e recusa de
  rollback depois de múltiplas projeções válidas do mesmo ticket.
- Ruff: `All checks passed`; 274 arquivos formatados.
- mypy: `Success: no issues found in 270 source files`.
- Django: zero issues; `makemigrations`: no changes detected.
- `git diff --check`: limpo.

## Decisão

Gate F tecnicamente verde. Isso não autoriza Gate G: deploy aditivo, dry-run ou
backfill compartilhado, alteração de flags, canário, enforcement e reparo do
incidente continuam exigindo aprovação separada.

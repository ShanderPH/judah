# Handoff

## Resumo implementado

- Removed all executable legacy customer-identification and triage entry points,
  agents, services, tasks, schedules, settings, manifests and tests.
- Preserved the generic lifecycle, service cycles, Matchmaker, queues, agents,
  calendar, metrics and shared HubSpot integrations.
- Added a forward migration that blocks active legacy work, narrows choices and
  removes only the exact obsolete Beat schedule without deleting history.
- Preserved independent RAG, knowledge and Salomao capabilities and added tests
  proving their startup and behavior.
- Replaced obsolete architecture documentation with the current JUDAH boundary
  and future n8n responsibilities; no n8n integration code was added.

## Arquivos modificados

The task-scoped diff covers `apps/ai_agents`, `apps/webhooks`, `core`, `common`,
the two HubSpot project manifests, requirements, scripts, README and docs. See
`git diff --name-status` for the complete inventory. Pre-existing deletions under
`ai-system/requests/hotfix/` and pre-existing untracked files were not touched.

## Como testar localmente

```powershell
.venv\Scripts\python.exe run_checks.py
.venv\Scripts\python.exe run_tests_local.py
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
```

For mypy, use the same safe test environment from `run_checks.py`, then run:

```powershell
.venv\Scripts\mypy.exe apps core common
```

## Riscos conhecidos

- Before applying migration 0008 in any shared environment, repeat the read-only
  preflight. It intentionally aborts if legacy states or active Heimdall sessions
  exist.
- HubSpot subscriptions/scopes remain unchanged externally until the versioned
  manifests are deliberately published.
- Supabase reported four Help Desk calendar tables without RLS, a pre-existing
  issue outside this refactor.
- The remote database reported PostgreSQL 17.6.1 while repository documentation
  declares PostgreSQL 16.

## Pontos críticos para review

- HubSpot NOVO/CLOSED/owner events still reach assignment/closure paths.
- Conversation messages are durable but produce no bot effect.
- Beat keeps the generic watchdog and removes only the legacy retry dispatcher.
- No `/api/v1/ai/` router or removed task is importable.

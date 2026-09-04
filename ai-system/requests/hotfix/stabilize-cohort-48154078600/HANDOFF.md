# HANDOFF — stabilize cohort 48154078600

## Resumo

- `OperationalWindow` tipada e half-open no calendário autoritativo.
- `OpeningAssignmentCohort` + migration `0030`, índice, RLS e grants runtime.
- Gate antes de readback/reserva no caminho comum, com bypass pós-abertura.
- Callback pós-commit, fallback Beat, modos off/shadow/enforce e telemetria PII-free.
- Cobertura local, PostgreSQL concorrente e worker/Redis real concluídos.

## Arquivos

`apps/support/{helpdesk_calendar/service.py,models.py,opening_cohort_service.py,durable_assignment_service.py,matchmaker_service.py,tasks.py,assignment_readiness.py}`, migration/testes correspondentes, `core/settings/base.py` e `conftest.py`.

## Teste local

```powershell
$env:DJANGO_ENV='test'
$env:DATABASE_URL='sqlite:///./.test.sqlite3'
$env:DJANGO_SECRET_KEY='test-only'
.venv\Scripts\python.exe -m pytest apps/support/tests/test_opening_cohort_barrier.py -vv
.venv\Scripts\python.exe -m pytest --cov=apps --cov=common --cov-report=term-missing
.venv\Scripts\python.exe -m ruff check apps/support core/settings conftest.py --no-cache
.venv\Scripts\python.exe -m mypy apps/support core/settings
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

## Riscos e integração

ETA é acelerador; Beat permanece fallback. Manter modo off até R0/R1 e aprovação de shadow/enforcement.
VERIFY deve atacar primeiro migration/RLS com role owner, alinhamento de SHA e zero attempt/PATCH durante defer.

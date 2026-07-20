# Local verification

Date: 2026-07-17
Database: local SQLite only
Production mutations: none

## Results

- `uv run ruff check .`: passed.
- `uv run mypy .`: passed, 239 source files.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `uv run python run_tests_local.py`: 393 passed.
- Coverage: 64.03%, above the configured 50% gate.
- `git diff --check`: passed.

## New regression coverage

- staging cannot call HubSpot or mutate shared availability;
- a foreign owner cannot release the SAT lease;
- active out-of-office wins over `available`;
- shadow decisions do not change legacy routing;
- stable-online promotion requires the configured samples/window;
- missing remote status fails closed;
- manual `status_enum=online` cannot create eligibility;
- the final guard prevents the HubSpot assignment call after an eligibility
  race;
- the client requests every required Users API `2026-03` property.
- ticket-triggered assignment forces an uncached Users API reconciliation;
- a Users API/reconciliation failure keeps the ticket queued;
- the assignment-critical client read bypasses a cached `available` value.
- the selected agent is read again by HubSpot user ID before reservation;
- remote `away` vetoes assignment after candidate selection;
- repeated identical final checks are read-only and do not change the SAT
  revision;
- missing/failed individual user reads fail closed.

## Verification limitation

PostgreSQL trigger behavior was not executed against a non-local database
because repository policy requires explicit approval for such tests.
Migration generation/state is locally consistent and the trigger migration is
vendor-gated to PostgreSQL.

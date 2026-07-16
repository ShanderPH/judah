# Verification report

Date: 2026-07-16

## Automated checks

- `ruff check .` — passed.
- `ruff format --check .` — passed (277 files).
- `git diff --check` — passed.
- `python -m mypy .` — passed (274 source files).
- `python run_checks.py` — migrations, missing migration check, and Django
  system checks passed.
- Local SQLite pytest run — 599 tests passed; 91.40% coverage, above the
  configured 90% enforcement floor.

## Acceptance evidence

- Raw and normalized event deduplication are covered by tests.
- Canonical routing controls a single dispatch path.
- Missing-data, candidate-resolution, confirmation, handoff, audit, signature,
  watchdog, and retry paths are covered.
- HubSpot v3 validation includes official field order, Base64 digest, URI
  decoding, and five-minute replay protection.

## Read-only credential smoke checks

- OpenAI models, HubSpot account info, Jira current user, Salomao health,
  Pinecone index stats, and the Supabase REST root all returned HTTP 200.
- The supplied production environment was never loaded into pytest and no
  external write or production database query was executed.

## Not executed

- Mutating production end-to-end scenarios were intentionally not executed.

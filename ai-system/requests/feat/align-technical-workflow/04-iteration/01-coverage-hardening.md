# Coverage hardening

Date: 2026-07-16

## Outcome

- Coverage increased from 62.86% to 91.40%.
- Test count increased from 397 to 599.
- After integrating the existing staging-only runtime and sandbox changes, the
  combined branch passes 631 tests with 91.27% coverage.
- The local and CI enforcement floor increased from 50% to 90%.
- No coverage exclusions or artificial omissions were added.

## Main areas added

- AI agent orchestration, webhooks, tasks, RAG, MCP, HubSpot hydration, and
  Salomao/InChurch adapters.
- Support APIs, services, auto-assignment, queue tasks, and management
  commands.
- HubSpot, Jira, Pinecone, Supabase, and Salomao provider clients.
- Authentication services and direct API branches.
- Common logging, rate limiting, circuit breaking, and health endpoints.

## Regression fixes found by tests

- Support ticket lookup now falls back from invalid UUID input to external
  ticket ID lookup.
- Special schedule creation now accepts the schema's parsed `date` value
  directly.

## Safety

- Tests run only against the private local SQLite database configured by
  `run_tests_local.py`.
- Production credentials were used only for read-only HTTP smoke checks and
  were never printed or persisted in the repository.

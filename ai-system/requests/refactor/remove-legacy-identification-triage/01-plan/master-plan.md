# Removal plan

## Objective

Remove the executable legacy customer-identification and triage implementation
without introducing any n8n contract or changing valid Help Desk operations.

## Ordered work

1. Remove AI HTTP entry points, HubSpot legacy dispatch and exclusive webhook
   subscriptions.
2. Remove legacy agents, schemas, identity services, pipelines, batching,
   reconciliation and recovery commands/tasks.
3. Reduce lifecycle routing and state transitions to preserved operational
   responsibilities; retain historical records.
4. Remove exclusive settings, Celery routes, dependencies and dead consumers.
5. Add a forward migration that rejects active legacy states before narrowing
   Django choices; do not delete data or edit applied migrations.
6. Replace legacy tests with absence assertions and rerun operational suites.
7. Update architecture and service documentation with the future JUDAH/n8n
   responsibility boundary, without implementation details or placeholders.

## Acceptance gates

- Django settings, URL configuration and Celery app import successfully.
- No legacy endpoint, task, schedule or executable import remains.
- Matchmaker, agents, queues, lifecycle and preserved HubSpot tests pass.
- `makemigrations --check`, ruff, mypy and the viable full suite pass.
- Residual semantic references are classified as migration history, intentional
  architecture history, preserved independent capability or false positive.

## Safety

- All tests use the repository's local SQLite isolation wrapper.
- No external write, commit, push or deployment is performed.
- Existing unrelated worktree changes are not staged, restored or edited.

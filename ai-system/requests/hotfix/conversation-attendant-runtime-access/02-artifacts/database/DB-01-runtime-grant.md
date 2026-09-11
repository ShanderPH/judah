# DB-01 — acesso do runtime ao histórico de atendentes

A migration 0032 concede `SELECT, INSERT, UPDATE` em `public.conversation_instance_attendants` apenas
aos papéis `judah_production_runtime` e `judah_staging_runtime` que existirem. Ela não altera owner, RLS,
policies, privilégios de `PUBLIC`, `anon` ou `authenticated`.

O rollback revoga exatamente os três privilégios concedidos. A operação é idempotente no PostgreSQL:
`GRANT` e `REVOKE` podem ser repetidos sem duplicar estado ou dados.

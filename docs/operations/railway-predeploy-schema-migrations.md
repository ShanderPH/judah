# Railway pre-deploy schema migrations

The Railway `judah` service runs `python manage.py railway_predeploy` before
promotion. Application runtime credentials intentionally do not own the
Supabase `public` schema, so schema-changing migrations must use a separate
privileged connection.

Configure `JUDAH_SCHEMA_DATABASE_URL` only on the Railway service that runs
the pre-deploy command. Keep `DATABASE_URL` unchanged for API, worker, and
beat runtime traffic. The command does not print either URL.

The migration URL must be supplied through Railway secrets and must be a
privileged Supabase connection that can create and alter schema objects. Do
not use `--fake`: the physical schema must exist before the application code
that references it is promoted.

Validation after configuring the secret:

1. Run a deploy and confirm `ai_agents.0007...` completes with `OK`.
2. Confirm the deployment health check is successful.
3. Confirm API, worker, and beat use the normal runtime `DATABASE_URL`.
4. Verify the migration row and the physical table through the approved
   privileged Supabase read path.

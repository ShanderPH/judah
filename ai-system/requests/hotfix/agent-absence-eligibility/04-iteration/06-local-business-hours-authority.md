# Iteration 06 — local business-hours authority

## Production finding

After Gate F enforcement, all six active agents converged to
`ineligible/malformed_remote_data`. HubSpot returned availability status but
did not return `hs_working_hours` or `hs_standard_time_zone`.

This is expected for JUDAH's operating model: HubSpot is authoritative for
account identity, `available`/`away`, and out-of-office intervals. The local
JUDAH calendar is authoritative for working hours and timezone.

## Correction

- Normalize HubSpot observations without requiring remote working hours or
  timezone.
- Continue to fail closed for missing identity, unknown availability, malformed
  absence intervals, and active out-of-office intervals.
- Evaluate working hours through `BusinessHoursConfig` and `SpecialSchedule`.
- Apply the same local schedule veto during assignment-time HubSpot
  revalidation.
- Treat configured holidays as Sunday hours unless an explicit
  `SpecialSchedule` overrides the date.

## Confirmed production configuration

- Monday through Friday: 09:00–18:00.
- Saturday: 09:00–13:00.
- Sunday and holidays: 08:00–12:00.
- Timezone: `America/Sao_Paulo`.

Tercio Augusto was configured independently with:

- active: yes;
- automatic assignment: enabled;
- maximum simultaneous chats: 4.

## Verification

- Focused suite: `46 passed`.
- Full local isolated suite: `434 passed, 3 skipped`.
- Coverage: `64.76%` against the required `50%`.
- Ruff lint and format: clean.
- mypy on changed source modules: clean.
- `git diff --check`: clean.

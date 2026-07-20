# Backend implementation walkthrough

## Incident closure

`docs/evidences/logs.txt` identifies staging as the second writer. Between
`19:41:24Z` and `19:42:45Z`, staging repeatedly:

1. fetched 28 HubSpot users;
2. changed Nathan from `away` to `online`;
3. dispatched the Matchmaker drain.

The staging process stopped at `19:42:56Z`. A read-only production query at
`20:55:43Z` found no Nathan status transition after that shutdown. Nathan
remained `away` with `auto_assign_enabled=true`.

## Implemented protocol

- Runtime authority fence blocks staging before SAT, queue sync, or Matchmaker.
- PostgreSQL triggers reject routing-state writes from non-authoritative JUDAH
  `application_name` values.
- HubSpot Users API `2026-03` supplies availability, out-of-office, individual
  working hours, timezone, and immutable account-scoped user ID.
- Typed normalization fails closed on missing or malformed required data.
- Database lease, owner token, TTL, and fencing generation serialize SAT.
- Every observation records writer, task, revision, hash, environment, and
  decision reason.
- Promotion requires two samples and 30 seconds; demotion is immediate.
- Queue selection requires fresh persisted eligibility when enforcement is on.
- Matchmaker locks and re-evaluates the candidate with the database clock,
  then reserves capacity before the HubSpot owner mutation.
- Failed external mutations compensate the capacity reservation.
- O falso webhook de disponibilidade de contato foi removido. A HubSpot não
  publica mudanças de `hs_availability_status`; o webhook real de ticket NOVO
  força uma consulta sem cache à Users API antes de qualquer atribuição.
- Depois da seleção, o Matchmaker consulta diretamente o usuário escolhido e
  aplica o mesmo motor de ausência/status/horário como veto final idempotente.
- Essa leitura final não grava status nem incrementa revisões; o SAT contínuo
  permanece como único writer da conciliação.
- Admin/API status mutation was removed; direct database changes cannot bypass
  eligibility.

## Rollout posture

The implementation supports shadow-first rollout. Production defaults to
shadow evaluation without enforcement until the discrepancies have been
reviewed. Final enforcement is an explicit Railway variable change.

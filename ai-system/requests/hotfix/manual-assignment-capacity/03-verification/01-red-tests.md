# Reproduções antes da implementação

Base: `8a9f9ae00ca75a539617ac650bab4529e64cf4c1`, branch criada como primeira ação de implementação: `hotfix/manual-assignment-capacity`.

Python 3.14.4, SQLite local, nenhuma chamada real ao HubSpot.

```powershell
$env:JUDAH_TEST_DATABASE_URL='sqlite:///./.test.sqlite3'
$env:PYTEST_ADDOPTS='--no-cov apps/support/tests/test_manual_assignment_capacity.py'
.venv\Scripts\python.exe run_tests_local.py
```

Resultado anterior à implementação: **4 failed**, 4.16s.

- Transferência sem anterior: observado `(1, 0)`, esperado `(0, 1)`.
- Manual sem fila: observado 0, esperado 1.
- Fila `failed/hubspot_manual_owner_observed`: observado 0, esperado 1.
- Seleção real com carteira remota cheia: criada `AssignmentAttempt.RESERVED`, esperada ausência de reserva.

Não houve substituição de `_verify_candidates`. As fronteiras do provider foram simuladas. Após integração inicial, os mesmos quatro testes passaram (8.60s, SQLite). Essa execução não comprova concorrência.

A interface/ticket do incidente foi solicitada novamente durante a implementação. A reprodução acima demonstra defeitos locais, sem atribuir incidência ou frequência em produção.

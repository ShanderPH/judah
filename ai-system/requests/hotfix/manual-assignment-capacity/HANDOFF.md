# Handoff para verificação local

- Ocupação identificada por portal/ticket e reservas por tentativa/transferência; contador deriva da união, sem deltas legados em enforcement.
- Reconciliação confirma owner e estado fora da transação, compara revisões, rejeita snapshots antigos e preserva reserva ambígua.
- Integração com seleção automática/manual, retry, compensação, fechamento, webhook, transferência administrativa e writers periódicos.
- Migration 0031 aditiva com constraints, RLS, grants restritos e guards de escrita; default `off`; bootstrap explícito em `shadow`.

Base: `8a9f9ae00ca75a539617ac650bab4529e64cf4c1`. Branch: `hotfix/manual-assignment-capacity`. Exclusões e arquivos não rastreados anteriores preservados.

## Arquivos de domínio

Prefixo absoluto: `C:\Projetos Febrate\judah\`.

- `apps/support/{capacity_service,owner_reconciliation_service,models,durable_assignment_service,queue_service,tasks,admin_api,auto_assign_service,sat_service,agent_sync_service,matchmaker_service,assignment_readiness,availability_runtime}.py`
- `apps/support/migrations/0031_ticket_capacity.py`
- `apps/support/management/commands/bootstrap_support_capacity.py`
- `apps/integrations/hubspot/client.py`, `core/settings/base.py`
- Testes novos: `apps/support/tests/test_{manual_assignment_capacity,capacity_postgres,capacity_celery}.py`, `apps/integrations/tests/test_hubspot_capacity_search.py`.

## Reprodução local

Infra isolada já criada: `judah-capacity-pg` PostgreSQL 16 em `127.0.0.1:55432`, banco descartável `judah_test`; `judah-capacity-redis` Redis 8.6 em `127.0.0.1:56379`. O PostgreSQL usa trust apenas na porta de loopback do container descartável.

```powershell
$env:JUDAH_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/judah_test'
$env:JUDAH_TEST_REDIS_URL='redis://127.0.0.1:56379/0'
$env:JUDAH_CAPACITY_REDIS_URL='redis://127.0.0.1:56379/0'
$env:PYTEST_ADDOPTS='--no-cov apps/support/tests/test_manual_assignment_capacity.py apps/support/tests/test_capacity_postgres.py apps/support/tests/test_capacity_celery.py apps/integrations/tests/test_hubspot_capacity_search.py'
.venv\Scripts\python.exe run_tests_local.py
```

Para suíte completa, remover somente `PYTEST_ADDOPTS` desta sessão e executar o mesmo runner. Nunca apontar o runner para banco remoto. Python validado: 3.14.4.

## Riscos e prioridades de VERIFY

1. Reserva refletida no owner remoto deve continuar contando uma vez; timeout sem owner conclusivo não libera vaga.
2. Serialização por ticket antes de ciclo/fila/operação/agentes; observar última vaga, scan concorrente e dupla compensação.
3. `off/shadow` devem preservar decisões e contador legados; falha do shadow não impede o writer legado.
4. Search é descoberta com lag, não snapshot; ausência exige readback por ID. Máximo inicial: 200 IDs, orçamento de 20s por refresh e até duas buscas por segundo neste consumidor.
5. Custo real da carteira e concorrência com outros consumidores do provider exigem o gate externo de shadow. Os testes locais não provam SLA do HubSpot.
6. Sem interface/ticket real informado, as reproduções demonstram defeitos de código, não frequência ou causa única do incidente em produção.

Não há mudança de UI nem deploy nesta etapa. Publicação, staging, bootstrap remoto e enforcement permanecem gates externos separados.

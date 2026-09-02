# HANDOFF — INCIDENT-48108294672

## Resumo do implementado/corrigido

- Corrigida a persistência de `Agent.status_enum` contra o enum físico legado do PostgreSQL, mantendo atomicidade e egress em lote para os demais campos.
- Adicionado guard fail-closed imediatamente antes do PATCH de owner, com preservação de owner manual, stage/pipeline e readback obrigatório após resultado confirmado ou ambíguo.
- Fortalecidos compensação, finalização, repair bounded, fencing e capacidade exatamente uma vez.
- Ampliados readiness, métricas e sanitização dos sinks finais sem acoplar assignment à liveness da API.
- Corrigida a provenance de `WebhookEvent.source` sem alterar a chave de deduplicação ou fazer backfill implícito.
- Adicionado harness real Celery/Redis/PostgreSQL para overlap SAT e concorrência de reservas.

## Arquivos modificados

Consulte `03-verification/01-local-verification.md` e `git diff --name-only origin/main..HEAD`. O diff funcional contém 31 arquivos sob `apps/`, `common/` e `core/`; os artefatos desta request ficam neste diretório.

## Como testar localmente

Pré-requisitos: PostgreSQL 16 local em `localhost:5432`, Redis local em `localhost:6379`, banco descartável `judah_test` e as variáveis seguras de `run_tests_local.py`.

```powershell
$env:DATABASE_URL='postgresql://judah:judah_dev_password@localhost:5432/judah_test'
$env:JUDAH_TEST_REDIS_URL='redis://localhost:6379/13'
uv run pytest apps/support/tests/test_celery_assignment_integration.py apps/support/tests/test_owned_cache_lock.py apps/support/tests/test_sat_enum_contract_postgres.py apps/support/tests/test_durable_assignment_protocol.py apps/webhooks/tests/test_n8n_concurrency.py core/tests/test_celery_startup.py -q
uv run ruff check apps common core
uv run ruff format --check apps common core
```

Não executar esses testes contra URL remota. `test_sat_enum_contract_postgres.py` possui recusa adicional de backend/host/database não descartável.

## Riscos conhecidos / áreas frágeis

- O schema de produção continua temporariamente divergente (`agent_status_enum` físico versus `CharField`); a migration definitiva permanece fora deste hotfix.
- O read-before-write reduz TOCTOU, mas HubSpot não oferece CAS comprovado neste fluxo; conflito posterior é detectado por readback e enviado a repair.
- Alertas externos, thresholds e ownership ainda exigem configuração/aprovação operacional.
- `mypy 2.1.0` falha ao instanciar `NewSemanalDjangoPlugin`; lint, testes e pre-commit passam, mas o gate de type-check permanece aberto.
- INT-01 não pode avançar sem SP-06 confirmar a fonte/build HubSpot canônica; V-04 depende de sandbox autorizado.

## Pontos críticos para VERIFY

1. Confirmar que nenhum caminho `external_applied` finaliza sem readback.
2. Reexecutar a fixture enum e a suíte concorrente em PostgreSQL 16.
3. Validar que métricas e logs não carregam nomes, e-mails, payloads ou mensagens cruas de exceção.
4. Verificar que liveness permanece 200 quando apenas assignment está degradado.
5. Após autorização, executar SP-06 read-only antes de qualquer alteração no manifest/HubSpot.

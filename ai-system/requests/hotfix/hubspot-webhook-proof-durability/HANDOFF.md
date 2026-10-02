# Passagem para verificação

## Implementado

- Proof versionado, SHA-256 dos manifests de app e webhooks, Redis sem TTL.
- Validade fail-closed independente de age/stale; legacy sem fingerprint fica inválido.
- Comando valida ambos os exports; drift e erro de export invalidam evidência anterior.
- Eventos de runtime e assignment separados; demais gates preservados.
- Regressões unitárias, matchmaker/protocolo completo e TTL real Redis local.

## Arquivos de produção

Raiz do worktree: `/tmp/judah-webhook-proof`.

- apps/support/webhook_proof.py
- apps/support/provider_readiness.py
- apps/support/availability_runtime.py
- apps/support/matchmaker_service.py
- apps/support/auto_assign_service.py
- apps/support/management/commands/record_hubspot_webhook_readback.py
- apps/support/tests/test_webhook_proof.py

## Verificação local

Python 3.14.7 no venv original. Runner seguro `/tmp/judah-proof-run.py` força placeholders, settings test, base SQLite local ou PostgreSQL local descartável `judah_ci_20261002_1`. Nada remoto.

```bash
python3 /tmp/judah-proof-run.py -m pytest --cov=apps --cov=common --cov-fail-under=90 -q
python3 /tmp/judah-proof-run.py postgres -q
python3 /tmp/judah-proof-run.py -m ruff check .
python3 /tmp/judah-proof-run.py -m ruff format --check .
python3 /tmp/judah-proof-run.py -m mypy apps common core
python3 /tmp/judah-proof-run.py manage.py check --fail-level WARNING
python3 /tmp/judah-proof-run.py manage.py makemigrations --check --dry-run
JUDAH_PROOF_LOCAL_REDIS_TEST=1 python3 /tmp/judah-proof-run.py -m pytest apps/support/tests/test_webhook_proof.py::test_real_redis_stores_proof_without_ttl -q
```

## Integrações e riscos

Atacar primeiro TTL Redis, estado legacy, validação de ambos os manifests e durable assignment com capacity enforce. Integrar HEAD fixado 952ca9f de #134 e repetir suite com recovery de lifecycle.

Nenhuma migration. Redis pode ainda perder evidência por flush/eviction/falha de persistência: continua fail-closed. Stale não garante ausência de drift publicado após o readback; warning operacional pede nova coleta autoritativa. Durante release, substituir gravação inline antiga pela chamada do comando versionado com exports publicados atuais. Não executar nesta etapa.

Hooks all-files têm pendências antigas em install.cmd e cinco SVGs. Sem alterações nesses arquivos; hooks dos arquivos da request precisam passar.

## Resultado concluído

Request DONE no código 433106f, integrado com #134/952ca9f, sem conflitos. Suite SQLite: 1.054 passed (90,91%). PostgreSQL: 1.097 passed (91,12%). Sete opt-ins Redis/Celery executados separadamente e passaram. Webapp: lint/typecheck/66 testes/build padrão/audit passaram, ressalvas anteriores documentadas. Relatório completo: 03-verification/combined.md. Próximo passo de Felipe: revisar release.md e autorizar operação de release separadamente.

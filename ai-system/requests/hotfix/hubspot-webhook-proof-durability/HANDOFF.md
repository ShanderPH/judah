# Passagem para verificação

## Continuação atual — contrato privado

Esta seção substitui o estado concluído da validação histórica abaixo. Checkout atual: `/tmp/judah-proof-private`, branch `hotfix/hubspot-webhook-proof-durability`, integrada com main/4ec547d e #134/952ca9f.

- Manifests desejados vêm somente de `HUBSPOT_PROVIDER_CONFIG_JSON`; dados reais ficam fora do checkout público.
- Fingerprint inclui revisão e ambos os manifests completos; writer e runtime compartilham a fonte validada.
- Configuração inválida bloqueia assignment e informa readiness sem erro 500; erro simultâneo de configuração/export invalida a prova anterior.
- Testes usam contrato sintético; TTL=-1 confirmado em Redis local real.
- SQLite: 1.079 passed (91,05%). PostgreSQL: 1.122 passed (91,26%). Redis/Celery/PostgreSQL opt-ins: 6 passed. Ruff/format/mypy/Django/drift/hooks passaram.

Arquivos alterados nesta continuação, relativos à raiz absoluta `/tmp/judah-proof-private`: `apps/integrations/hubspot/webhook_config.py`, `apps/support/{webhook_proof.py,provider_readiness.py,management/commands/record_hubspot_webhook_readback.py,tests/test_webhook_proof.py,tests/test_provider_contract_red.py}`, `apps/webhooks/tests/test_production_project_config.py`, `core/settings/{base.py,test.py}` e os artefatos da request. Status/handoff do release provider foram sincronizados.

Comandos locais completos em `03-verification/private-config.md`, executados com placeholders e bases locais descartáveis. Primeiro VERIFY: configuração ausente/malformed, incompatibilidade de revisão/app/webhooks, invalidação conjunta e gravação sem TTL. Nenhum HMAC foi alterado; nenhuma leitura/escrita produtiva foi realizada.

Bloqueio independente do release: `reproduce-entry-overlap.py` confirma que uma execução atrasada de #134 abre um ciclo e troca `repair_required` por `processed`. Os módulos lifecycle de #134 permanecem intactos nesta continuação. Manter PR em draft até esse achado ser resolvido ou decidido explicitamente, além dos gates operacionais de `05-deployment/private-contract.md`.

## Evidência histórica anterior à remoção dos manifests

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

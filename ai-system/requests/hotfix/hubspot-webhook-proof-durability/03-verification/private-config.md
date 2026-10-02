# Verificação da continuação com contrato privado

## Resultado do proof

Continuação sobre `62da400`, que já contém main/4ec547d e #134/952ca9f. Ambiente Python 3.14.7. Nenhum manifest produtivo foi restaurado; nenhuma variável ou evidência produtiva foi consultada ou escrita.

- SQLite completo: **1.079 passed, 51 skipped**, cobertura **91,05%**.
- PostgreSQL 16 local completo: **1.122 passed, 8 skipped**, cobertura **91,26%**.
- Ruff lint/format, mypy (383 arquivos), Django system check e migration drift passaram.
- Hooks pre-commit dos nove arquivos de código alterados passaram.
- Caso real Redis do proof confirmou `TTL=-1` e igualdade do snapshot relido.
- Redis/Celery real com PostgreSQL local: **6 passed**, incluindo TTL, locks e entrega de tarefas.
- CI no código `9dc459f742739119c4141b9dba21feda70e40a6f`: **todos os cinco jobs passaram**, incluindo Python completo, webapp, lint/typecheck, segurança e Django/drift. Run: https://github.com/ShanderPH/judah/actions/runs/37039194032.
- Regressores direcionados iniciais: 93 passed, 2 skipped. A suíte completa posterior inclui os casos adicionais de subscriptions inválidas e ausência simultânea de configuração/readback.

O runner `/tmp/judah-private-check.py` usa apenas placeholders e força SQLite local ou PostgreSQL local descartável `judah_ci_2026100218_135`. O sandbox bloqueou sockets locais e a aquisição dos hooks; esses checks foram repetidos com autorização de execução. Um primeiro nome de base descartável não satisfazia o regex do guard runtime; apenas o nome do banco de testes foi ajustado, sem alterar guards. A integração Celery com SQLite encontrou lock; a validação real usa PostgreSQL.

## Contrato verificado

`HUBSPOT_PROVIDER_CONFIG_JSON` fornece revisão, app e webhooks completos. O loader rejeita configuração ausente, JSON inválido, seções incompletas, UIDs vazios, target inválido, concorrência inválida, subscriptions sem evidência ativa ou scopes inválidos. Os testes usam um contrato sintético definido exclusivamente nas settings de teste.

O hash canônico inclui a revisão e ambos os manifests completos. Provas antigas, incompatíveis, inválidas ou ausentes continuam bloqueando; age não invalida prova compatível. Readiness informa `desired_configuration_invalid` em vez de lançar 500. Writer invalida a prova anterior mesmo quando configuração e exports são inválidos simultaneamente. Erros são genéricos e o CLI não expõe nomes privados de scopes/propriedades.

## Revisão da integração

Sem diff em relação a #134/952ca9f nos módulos lifecycle e dependências do webapp. A verificação local do webapp anterior continua como evidência histórica; CI deverá reexecutá-la no SHA publicado desta continuação. Não houve mudança de UI.

O comentário de performance sobre leitura de arquivos por item deixa de aplicar à fonte atual, que não faz IO de arquivos. O hash ainda é recalculado a partir das settings em cada verificação; não foi acrescentado cache que pudesse reutilizar identidade após mudança de configuração.

## Bloqueio independente encontrado

O alerta de concorrência no ramo de entrada herdado de #134 foi reproduzido por `reproduce-entry-overlap.py`, executado explicitamente fora da suíte padrão. Uma execução pausa antes da projeção; outra consome o budget e grava `repair_required`; a primeira abre o ciclo e sobrescreve o terminal como `processed`. A assertion de preservação terminal falha: `assert 'processed' == 'repair_required'`.

Esse reproducer é evidência de defeito preexistente na integração, não uma aprovação de release. O proof está validado, mas o release conjunto precisa resolver esse alerta ou de uma decisão explícita de Felipe. A origem privada, aquisição publicada nova, substituição do writer legado e autorização operacional também continuam necessárias.

## Comandos reproduzíveis neste host

```bash
/usr/bin/python3 /tmp/judah-private-check.py -m pytest --cov=apps --cov=common --cov-fail-under=90 -q
/usr/bin/python3 /tmp/judah-private-check.py postgres -m pytest --cov=apps --cov=common --cov-fail-under=90 -q
/usr/bin/python3 /tmp/judah-private-check.py postgres redis -m pytest apps/support/tests/test_webhook_proof.py::test_real_redis_stores_proof_without_ttl apps/support/tests/test_owned_cache_lock.py apps/support/tests/test_celery_assignment_integration.py --no-cov -q
/usr/bin/python3 /tmp/judah-private-check.py -m ruff check .
/usr/bin/python3 /tmp/judah-private-check.py -m ruff format --check .
/usr/bin/python3 /tmp/judah-private-check.py -m mypy apps common core
/usr/bin/python3 /tmp/judah-private-check.py manage.py check --fail-level WARNING
/usr/bin/python3 /tmp/judah-private-check.py manage.py makemigrations --check --dry-run
/usr/bin/python3 /tmp/judah-private-check.py -m pytest ai-system/requests/hotfix/hubspot-webhook-proof-durability/03-verification/reproduce-entry-overlap.py --no-cov -q
```

O último comando é uma reprodução negativa e deve falhar na árvore atual. Todos os testes conectam somente bases locais descartáveis. Nenhuma execução em base não-local foi realizada.

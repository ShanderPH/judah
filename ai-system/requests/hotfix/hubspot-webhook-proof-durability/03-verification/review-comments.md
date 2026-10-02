# Validação dos comentários do PR #135

Baseline revisado: `edc50303f2b825e382b8b56ca4a498a2c98907db`. Comentários inline e review geral lidos pela API do GitHub. Escopo autorizado: corrigir achados confirmados, sem merge/deploy ou escrita produtiva.

| Comentário | Veredicto | Resultado |
|---|---|---|
| 4167836624 — status/handoff do provider | Já atendido na continuação privada | Revalidado e atualizado para o release conjunto e a correção atual. |
| 4167836629 — invalidar proof quando configuração/export falham | Já atendido em 9dc459f | Regressão conjunta permanece na suíte completa. |
| 4167836638 — projeção após repair_required | Confirmado | Releitura e lock transacional cobrem elegibilidade/projeção; mark_processed exige pending. |
| 4167836649 — custo repetido do fingerprint | Parcialmente confirmado | IO de arquivos já removido; parsing/hash repetidos corrigidos com cache de uma entrada, indexado pela configuração atual. |
| 4168844881 — tipo da fixture no replay | Confirmado | Settings concreto no replay e nos novos testes que usam settings. |
| 4168844892 — cronologia do status | Confirmado | last_update agora representa a revisão posterior a opened_at; nenhum horário histórico foi inventado. |

## Review geral 5956305255

- Concorrência: confirmada e corrigida como acima.
- Drift publicado após readback: limitação real do desenho aprovado sem TTL, sem detecção automática. Preparação operacional agora explicita dono, serialização e readback autoritativo após qualquer publicação; não foi introduzida renovação cega nem monitoramento adicional.
- Sintaxe de except: não confirmado. Python 3.14.7 compila os módulos que usam a sintaxe permitida nessa versão; os testes os importam e executam.
- Docstrings: ausência confirmada em 20 testes públicos alterados; documentados os contratos desses testes. Não alteramos funções fora do diff.

## Evidência antes/depois

- Replay original no baseline: falhou com `processed != repair_required`.
- Duas regressões permanentes no baseline: falharam, incluindo confirmação atrasada sobrescrevendo repair_required.
- Contenção real PostgreSQL no baseline: falhou porque a segunda conexão não aguardava o lock da projeção.
- Após correção: módulo lifecycle em PostgreSQL, **15 passed**; targeted proof/lifecycle/replay em SQLite, **63 passed, 2 skipped**. O replay explícito agora passa e chama a regressão permanente, sem duplicar sua implementação.
- O teste PostgreSQL usa duas conexões e consulta pg_blocking_pids para comprovar bloqueio, depois verifica duas respostas processed, retry_count=1 e um único ciclo. SQLite não demonstra row locks.
- Cache: chamadas repetidas analisam uma vez; revisão diferente gera outro hash e uma nova análise; configuração inválida levanta ValueError e não reutiliza hash antigo.

## Verificação final

- SQLite: **1.082 passed, 52 skipped**, cobertura **91,05%**.
- PostgreSQL 16 local: **1.126 passed, 8 skipped**, cobertura **91,26%**.
- Redis/Celery/PostgreSQL locais: **6 passed**, incluindo proof relido com **TTL=-1**.
- Replay explícito da concorrência: **1 passed** na árvore corrigida.
- Ruff lint e format: passaram (387 arquivos formatados).
- Mypy: passou, sem issues em 383 arquivos de produção.
- Compilação Python 3.14.7, Django system check e migration drift: passaram.
- Hooks pre-commit dos arquivos desta revisão: passaram; diff desta iteração parseável por git apply --stat.
- Auditoria AST: nenhuma função pública sem docstring nos três módulos de testes desta revisão.

CI do novo SHA é obrigatória antes do release; consultá-la no PR #135. Nenhuma alteração de UI foi feita nesta revisão; o job WebApp da CI valida a integração existente.

## Comandos exatos neste host

O runner `/tmp/judah-private-check.py` invoca o venv Python 3.14.7 com placeholders e SQLite local ou PostgreSQL 16 local descartável `judah_ci_2026100218_135`; Redis local usa a base 15. Nenhum teste remoto.

```bash
/usr/bin/python3 /tmp/judah-private-check.py -m pytest --cov=apps --cov=common --cov-fail-under=90 -q
/usr/bin/python3 /tmp/judah-private-check.py postgres -m pytest --cov=apps --cov=common --cov-fail-under=90 -q
/usr/bin/python3 /tmp/judah-private-check.py postgres redis -m pytest apps/support/tests/test_webhook_proof.py::test_real_redis_stores_proof_without_ttl apps/support/tests/test_owned_cache_lock.py apps/support/tests/test_celery_assignment_integration.py --no-cov -q
/usr/bin/python3 /tmp/judah-private-check.py -m pytest ai-system/requests/hotfix/hubspot-webhook-proof-durability/03-verification/reproduce-entry-overlap.py --no-cov -q
/usr/bin/python3 /tmp/judah-private-check.py -m ruff check .
/usr/bin/python3 /tmp/judah-private-check.py -m ruff format --check .
/usr/bin/python3 /tmp/judah-private-check.py -m mypy apps common core
/usr/bin/python3 /tmp/judah-private-check.py -m compileall -q apps/support/webhook_proof.py apps/integrations/hubspot/webhook_config.py
/usr/bin/python3 /tmp/judah-private-check.py manage.py check --fail-level WARNING
/usr/bin/python3 /tmp/judah-private-check.py manage.py makemigrations --check --dry-run
```

Preservados budgets, scanner limitado e todos os gates do assignment. Transação nova contém somente operações no banco. Rollout privado e readback novo, substituição do writer legado, validação do SHA final e autorização de Felipe continuam pendentes para o release conjunto.

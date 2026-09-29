# Verificação local — contrato HubSpot / lifecycle

Data: 2026-09-29. Base: `62fb21518cd0c0726c80a1050927b268a708912d`. Branch: `refactor/hubspot-provider-contract-2026-09`.

| Gate | Resultado | Evidência |
|---|---|---|
| Suíte completa SQLite local | 982 passaram, 47 pulados | `DJANGO_ENV=test DATABASE_URL=sqlite:///./.test.sqlite3 SALOMAO_V1_BASE_URL='' .venv/bin/python -m pytest -q` |
| Ruff | limpo | `.venv/bin/ruff check apps/integrations/hubspot apps/support apps/webhooks core/settings/base.py` |
| Ruff global / formatação | limpos, 378 arquivos formatados | `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` |
| Mypy | limpo, 376 arquivos | `.venv/bin/mypy .` |
| Pre-commit nos arquivos da PR | limpo | `python -m pre_commit run --files` aplicado à lista staged; os ajustes automáticos foram incorporados |
| Django check / migration drift / diff check | limpos | `manage.py check`, `makemigrations --check --dry-run`, `git diff --check` |
| PostgreSQL local: reserva concorrente e fechamento concorrente | 4 passaram | testes de `test_capacity_postgres.py` e `test_ticket_close_service.py` com banco PostgreSQL local |
| PostgreSQL local: RLS/trigger da ocorrência | 1 passou | `test_occurrence_table_has_postgres_runtime_guard` com migration `0033` |
| PostgreSQL 16 local: migration `0035` | forward, reverse, forward e 2 INSERTs nulos passaram | Banco descartável `judah_ci_20260929_1`, removido após teste; consulta `information_schema` retornou `YES` nas duas colunas; INSERTs dentro de `BEGIN/ROLLBACK` retornaram 1/1. |
| PostgreSQL local: ocorrência, transferência e schemas nulos | 5 passaram | `test_provider_contract_red.py` dirigido contra banco `test_` descartável criado pelo pytest-django |
| PostgreSQL + Redis + worker Celery locais | 1 passou | `test_capacity_celery.py` com Redis local e worker real |

O valor de `SALOMAO_V1_BASE_URL` neutraliza uma configuração local que faz um teste não relacionado falhar. Nenhum teste desta request foi conectado a banco não local.

## Cobertura nova

- Preflight diferencia 401, 403, 429, 5xx e ausência de prova de escrita.
- Roster verifica 0, 1, 100 e 101 membros, cursor parcial, deduplicação e erro remoto.
- Fechamento sem horário fica pendente; readback posterior converge uma vez; budget esgotado sinaliza reparo.
- Owner antes do ciclo não cria métrica temporal; entrada comprovada permite convergência.
- Owner webhook com horário comprovado gera ocorrência antes da projeção; sem ciclo comprovado fica pendente para reconciliação bounded. Ocorrência anterior ao ciclo atual não reivindica esse ciclo. Falha 401/403 exige reparo sem descartar evidência `proven`. Snapshot sem horário de assignment/transferência persiste nulo, sem inventar duração.
- `enforce` recusa efeitos de owner se o writer canônico de capacidade não estiver ativo.
- Métricas em `enforce` contam os ciclos de um ticket reaberto separadamente e deduplicam fechamento e log. Transferência só conta para owner anterior quando há mensagem outbound humana dele antes da transferência, durante sua posse, no mesmo portal/ticket/ciclo. Mensagem de outro ator, posterior à transferência ou do bot não serve. Em uma cadeia de duas transferências, o agente intermediário só conta se respondeu durante sua posse.
- `threadAssociations` em lista associa um único ticket à mensagem; associações com tickets diferentes ficam sem ticket. Testes de ingestão e reconciliação: 21 passaram após essa correção.
- Schemas Ninja de atribuição e transferência aceitam `NULL` nos horários que a migration `0035` tornou opcionais.
- Reserva durável em capacidade `enforce` não sobrescreve contagem recalculada por projeção concorrente.
- Drift de manifesto/app bloqueia readiness; efeito externo sem evidência fica `unknown_external`.
- Adapter de Tickets testa leitura, PATCH e classificação HTTP sem chamada remota real.

## Gates ainda abertos

1. V-03: validar em sandbox HubSpot os paths e payloads reais de Tickets 2026-09, Teams, Users, Owners, stage e reopen; comprovar escrita com uma mutation de ticket sandbox autorizada separadamente.
2. Conferir scopes efetivos com least privilege e fazer readback da configuração publicada de app/webhooks; o comando local só compara exports fornecidos pelo operador.
3. Observar shadow em janela representativa, incluindo pending, ciclos, provenance, divergências e 429.
4. Fechar ARCH-03: comparar writers legados de owner/contadores com o fluxo `enforce` e validar amostra real de ator/mensagem/transferência. Respostas anteriores à implantação da prova não foram reprocessadas; ausência de prova reduz a contagem do agente anterior. Medir custo da agregação histórica em shadow.
5. Reverse de `0035` só foi validado em banco vazio: após persistir horários nulos, não usar reverse como rollback.
6. Exercitar rollback em ambiente seguro e executar dry-run histórico apenas após cutover estável.

**Conclusão:** a implementação local está verificável; o P0 e o rollout não estão concluídos.
